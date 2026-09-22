"""Worker : exécute les recherches mises en file depuis la console du site.

    python -m sortiesbot.worker            # boucle, une passe toutes les 30 s
    python -m sortiesbot.worker --once     # traite au plus une exécution

Le worker ne décide de rien. Il réclame le travail en attente
(`POST /api/scraper/next`), joue le pipeline avec la configuration que le site
lui donne, rend compte page par page (`/runs/:id/items`) puis clôt l'exécution
avec ses compteurs (`/runs/:id/finish`). Tout le reste — créer une recherche,
la lancer, la relire — se passe dans la console.

Sur le VPS il tourne en service systemd (voir deploy/README.md) : c'est lui
qui doit être démarré pour que le bouton « Lancer » de la console fasse
quelque chose.
"""

from __future__ import annotations

import argparse
import faulthandler
import hashlib
import signal
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from .api import ApiError, SppApi
from .chasse import hunt
from .config import (
    IDF_POSTAL_PREFIXES,
    PROVIDERS,
    Config,
    ConfigError,
    Environment,
    config_from_api,
    load_dotenv,
)
from .evaluation import (
    capture_pages,
    extract_page,
    harvest_from_html,
    read_from_html,
    select_from_html,
)
from .harvest import Fetcher
from .journal import RemoteJournal, RunLog, run_log_path
from .ledger import Ledger, ledger_path
from .models import Summary
from .orchestrator import run as run_pipeline
from .orchestrator import run_source
from .providers.base import ProviderError, get_provider
from .providers.openrouter_provider import EFFORTS, modele_openrouter
from .providers.serper_client import client_or_none
from .store import RemoteStore

ROOT = Path(__file__).resolve().parent.parent

#: Dossier du registre du classifieur. Volontairement hors de `runs/` : les
#: journaux d'exécution s'oublient depuis la console du site, cette mesure doit
#: s'accumuler sur des semaines. Un fichier horodaté par exécution.
LEDGER_DIR = ROOT / "state"

#: Attente entre deux passages à vide. Une recherche dure des minutes ; une
#: demi-minute de latence au démarrage ne se voit pas dans la console.
POLL_SECONDS = 30

#: Attentes avant chaque nouvelle tentative de clôture. C'est le seul appel du
#: worker qu'on ne peut pas perdre : sans lui l'exécution reste « En cours »
#: dans la console et bloque toute nouvelle exécution de la configuration,
#: jusqu'à une annulation à la main. Les reprises de connexion de la session
#: (`api.retrying_session`) couvrent la seconde ; celles-ci couvrent la minute
#: — le temps qu'une API redémarrée réponde à nouveau.
FINISH_DELAYS = (2, 4, 8)

_stop = False


def _handle_signal(*_args: object) -> None:
    """Arrêt propre : on finit l'exécution en cours, on ne prend pas la suivante."""
    global _stop
    _stop = True
    print("Arrêt demandé : le worker s'arrêtera après l'exécution en cours.", flush=True)


def open_log(
    runs_dir: Path,
    name: str,
    quiet: bool,
    sink: Callable[[dict[str, Any]], None] | None = None,
) -> RunLog:
    """Ouvre le journal fichier du run, en insistant un peu.

    Un dossier `runs/` devenu illisible — typiquement créé par root lors d'un
    essai en ligne de commande, alors que le service tourne en `deploy` — ne
    doit pas faire échouer une recherche. Mais s'en passer entièrement, comme
    avant, laissait le run sans aucune trace fichier : on se rabat donc sur un
    dossier temporaire, qui est toujours accessible, avant d'abandonner.

    Le `sink` est l'autre destination du journal : le site, qui l'affiche dans
    sa page de débogage.
    """
    candidates = [runs_dir, Path(tempfile.gettempdir()) / "sortiesbot-runs"]
    for index, directory in enumerate(candidates):
        try:
            log = RunLog(run_log_path(directory, name), verbose=not quiet, sink=sink)
        except OSError as err:
            print(
                f"Journal impossible dans {directory} ({err}).",
                file=sys.stderr,
                flush=True,
            )
            continue
        if index and not quiet:
            print(f"  journal replié sur {log.path}", flush=True)
        return log
    print(
        "Aucun journal fichier : le run continue, le site garde le sien.",
        file=sys.stderr,
        flush=True,
    )
    return RunLog(None, verbose=not quiet, sink=sink)


def counters(summary: Summary) -> dict[str, Any]:
    """Compteurs du run tels que la console les affiche."""
    return {
        "candidates": summary.candidates,
        "pages": summary.pages,
        "nextPages": summary.next_pages,
        "retained": summary.retained,
        "submitted": summary.submitted,
        "duplicates": summary.duplicates,
        "skipped": (
            summary.skipped_seen
            + summary.skipped_blocked
            + summary.skipped_irrelevant
            + summary.skipped_invalid
        ),
        "errors": summary.errors,
        "inputTokens": summary.usage.input_tokens,
        "outputTokens": summary.usage.output_tokens,
        "webSearches": summary.usage.web_searches,
        "costUsd": round(summary.usage.total_usd, 4),
    }


def finish(
    api: SppApi,
    run_id: int,
    status: str,
    payload: dict[str, Any],
    quiet: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Clôt l'exécution, et insiste : c'est ce qu'on ne peut pas perdre.

    Une clôture perdue ne se rattrape pas — personne ne repasse fermer un run,
    et la configuration reste bloquée. Un déploiement du site suffisait à en
    arriver là : l'API redémarre, la clôture tombe sur une connexion refusée,
    le worker enchaîne. On réessaie donc, de plus en plus loin.

    Rend vrai si le site a pris la clôture. Faux, le worker continue de toute
    façon : le run suivant ne doit pas payer l'échec du précédent, et le
    serveur ferme d'office les exécutions dont il n'a plus de nouvelles.
    """
    last: Exception | None = None
    for attempt, delay in enumerate((0.0, *FINISH_DELAYS)):
        if delay:
            sleep(delay)
        try:
            api.finish_run(run_id, status, **payload)
            if attempt and not quiet:
                print(f"  clôture obtenue au {attempt + 1}e essai.", flush=True)
            return True
        except ApiError as err:
            last = err
    print(
        f"Clôture impossible de l'exécution #{run_id} après {len(FINISH_DELAYS) + 1} "
        f"essais : {last}. Le serveur la fermera d'office.",
        file=sys.stderr,
        flush=True,
    )
    return False


def execute(job: dict[str, Any], api: SppApi, env: Environment, runs_dir: Path, quiet: bool) -> None:
    """Joue une exécution réclamée au site, et la clôt quoi qu'il arrive.

    Le site l'a déjà passée en RUNNING : la laisser sans clôture la figerait
    dans la console, et bloquerait toute nouvelle exécution de la même
    configuration. D'où le `finally` — même sur une erreur imprévue.

    Deux sortes d'exécution passent par ici, et c'est le site qui les
    distingue : une exécution qui porte une **sortie** est une recherche de
    source — l'étage 7 rejoué seul, sur une fiche déjà publiée — et tout le
    reste est le pipeline entier. Elles partagent tout ce qui les entoure : le
    journal renvoyé au site, le registre, la clôture, les compteurs. Seule la
    ligne qui joue change, et elle est visible à l'œil nu ci-dessous.
    """
    run_id = int(job["id"])
    submit = bool(job.get("submit"))
    event = job.get("event") or None
    status, error = "FAILED", "Interrompu avant la fin"
    summary = Summary()

    try:
        config = config_from_api(job.get("config") or {})
    except ConfigError as err:
        # Même exigence qu'à la sortie normale : une configuration illisible
        # n'est pas une raison pour laisser la ligne « En cours » à vie.
        finish(api, run_id, "FAILED", {"error": str(err)}, quiet)
        return

    if not quiet:
        quoi = f"source de « {event.get('title')} »" if event else f"« {config.name} »"
        print(f"▶ Exécution #{run_id} — {quoi}", flush=True)

    store = RemoteStore(api, run_id)
    # Le journal détaillé part au site au fil de l'eau : c'est lui que la page
    # de débogage affiche, étage par étage.
    journal = RemoteJournal(api, run_id)
    try:
        provider = get_provider(
            config,
            api_key=env.anthropic_key,
            serper_key=env.serper_key,
            openrouter_key=env.openrouter_key,
        )
        with open_log(runs_dir, config.name, quiet, sink=journal.add) as log:
            if log.path and not quiet:
                print(f"  journal : {log.path}", flush=True)
            # Le service tourne des semaines : c'est lui qui alimente
            # vraiment le registre du classifieur, à côté des journaux de run
            # que le site peut oublier.
            with Ledger(ledger_path(LEDGER_DIR, run_id), run=str(run_id)) as ledger:
                # Le moteur du repli de l'attribution : présent dès qu'une clé
                # Serper l'est, quel que soit le fournisseur de la recherche
                # que la console a choisi.
                engine = client_or_none(env.serper_key)
                if event is None:
                    summary = run_pipeline(
                        config, provider, store, api, log, submit=submit,
                        ledger=ledger, engine=engine,
                    ).summary
                else:
                    found = run_source(
                        config, provider, store, api, log, event,
                        ledger=ledger, engine=engine,
                    )
                    summary = found.summary
                    # Le rapport fait partie du travail : une recherche qui
                    # trouve sans le dire n'a rien fait. S'il échoue, le run
                    # est en échec — et la fiche garde le lien qu'elle avait.
                    api.report_source(
                        run_id,
                        url=found.source.url,
                        signal=found.source.signal,
                        detail=found.source.detail,
                        checked=found.source.checked,
                        found_on=str(event.get("pageUrl") or ""),
                    )
        status, error = "DONE", None
    except ProviderError as err:
        error = str(err)
    except ApiError as err:
        error = str(err)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        error = f"{err.__class__.__name__} : {err}"
    finally:
        # Le journal d'abord : la console doit pouvoir montrer ce qui s'est
        # passé, y compris — surtout — quand l'exécution se termine en échec.
        journal.flush()
        try:
            store.flush()
        except ApiError as err:
            print(f"Journal du run incomplet : {err}", file=sys.stderr, flush=True)
        payload = counters(summary)
        if error:
            payload["error"] = error[:2000]
        finish(api, run_id, status, payload, quiet)
        if not quiet:
            done = "terminée" if status == "DONE" else f"en échec ({error})"
            print(f"■ Exécution #{run_id} {done} — {payload['costUsd']} $", flush=True)


def capture(job: dict[str, Any], api: SppApi, quiet: bool) -> None:
    """Gèle une entrée du corpus, et la clôt quoi qu'il arrive.

    Capturer n'est pas mesurer : on télécharge, on archive le HTML, on n'en
    tire aucun relevé. Ce que les briques rendent est l'affaire d'un run, qui
    rejouera plus tard sur ce qui vient d'être gelé — et c'est ce découplage
    qui rend deux runs comparables.

    Le `finally` a la même raison qu'ailleurs : le site a déjà passé l'entrée
    en RUNNING, et sans clôture elle ne serait plus jamais réclamée.
    """
    kind = str(job.get("kind") or "agenda")
    item_id = int(job["id"])
    url = str(job["url"])
    pages = int(job.get("pages") or 1)
    if not quiet:
        print(f"▶ Corpus — {kind} #{item_id} : {url} ({pages} page(s))", flush=True)

    reported = False
    try:
        gelees = capture_pages(url, pages, fetcher=Fetcher())
        api.report_capture(kind, item_id, gelees)
        reported = True
        if not quiet:
            poids = sum(p.get("chars", 0) for p in gelees)
            print(f"■ Corpus — {kind} #{item_id} : {len(gelees)} page(s), {poids} caractères", flush=True)
    except ApiError as err:
        print(f"Capture non rendue pour {kind} #{item_id} : {err}", file=sys.stderr, flush=True)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        if not reported:
            try:
                api.fail_capture(kind, item_id, f"{err.__class__.__name__} : {err}")
            except ApiError as api_err:
                print(f"Clôture impossible de {kind} #{item_id} : {api_err}", file=sys.stderr, flush=True)


#: Candidates rendues par envoi. Chacune porte son HTML gzippé : une trentaine
#: de pages d'un coup dépasserait le plafond de corps du site, et perdrait tout
#: le travail de la chasse pour un seul envoi refusé.
HUNT_BATCH = 5


def chasse(job: dict[str, Any], api: SppApi, env: Environment, quiet: bool) -> None:
    """Joue une chasse : les recherches de l'étage 1, la précoche de l'étage 2.

    C'est la seule file du banc qui touche au web vivant, et c'est assumé :
    elle **peuple** le corpus, elle ne le mesure pas. Le HTML est gelé au
    passage, de sorte que la page qu'un run rejouera plus tard est exactement
    celle sur laquelle la précoche a été faite.

    Les candidates partent par paquets, au fil de l'eau : une chasse
    interrompue laisse ce qu'elle a déjà trouvé, qui reste bon à valider.

    Le `finally` a la même raison qu'ailleurs — le site l'a déjà passée en
    RUNNING, et sans clôture elle ne serait plus jamais réclamée.
    """
    hunt_id = int(job["id"])
    config = _chasse_config(job)
    if not quiet:
        print(f"▶ Chasse #{hunt_id} — « {config.theme} »", flush=True)

    log = RunLog(None, verbose=not quiet)
    status, error = "DONE", None
    trouvees, hors_plafond = 0, 0
    # Celles **réellement lancées** : la console n'en impose pas toujours, et
    # une chasse qui tait les requêtes que le modèle a formulées ne se rejoue
    # pas — c'est le même manque qu'un run sans `codeRef`.
    requetes = list(config.queries)
    provider = None
    try:
        provider = get_provider(
            config,
            api_key=env.anthropic_key,
            serper_key=env.serper_key,
            openrouter_key=env.openrouter_key,
        )
        found = hunt(config, provider, log, fetcher=Fetcher())
        requetes = list(found["queries"])
        hors_plafond = int(found["overCap"])
        pages = found["pages"]
        for start in range(0, len(pages), HUNT_BATCH):
            paquet = pages[start : start + HUNT_BATCH]
            api.report_hunt_pages(hunt_id, paquet)
            trouvees += len(paquet)
    except (ProviderError, ApiError) as err:
        status, error = "FAILED", str(err)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        status, error = "FAILED", f"{err.__class__.__name__} : {err}"
    finally:
        usage = getattr(provider, "usage", None)
        payload: dict[str, Any] = {
            "queries": requetes,
            "pages": trouvees,
            "overCap": hors_plafond,
            "model": config.classify_model,
            "costUsd": round(float(getattr(usage, "total_usd", 0.0) or 0.0), 4),
        }
        if error:
            payload["error"] = error[:2000]
        try:
            api.finish_hunt(hunt_id, status, **payload)
        except ApiError as err:
            print(f"Clôture impossible de la chasse #{hunt_id} : {err}", file=sys.stderr, flush=True)
        if not quiet:
            fin = "terminée" if status == "DONE" else f"en échec ({error})"
            print(
                f"■ Chasse #{hunt_id} {fin} — {trouvees} candidate(s), "
                f"{payload['costUsd']} $",
                flush=True,
            )


def _chasse_config(job: dict[str, Any]) -> Config:
    """La configuration **que la chasse déclare**, et rien d'inventé ici.

    Le prompt devient le thème : c'est lui qui part dans les requêtes, et c'est
    tout ce dont l'étage 1 a besoin. Le reste — la zone, le plafond, le moteur
    — vient de la console, où un humain l'a fixé.
    """
    return Config(
        name="chasse",
        theme=str(job.get("prompt") or "sorties enfants"),
        area=str(job.get("area") or "Île-de-France"),
        queries=[str(q) for q in (job.get("queries") or [])],
        max_searches=int(job.get("maxQueries") or 6),
        max_agendas=int(job.get("maxPages") or 30),
        provider=str(job.get("provider") or "serper"),
    )


def _bench_config() -> Config:
    """La configuration de repli du banc.

    Ne sert plus qu'aux runs mis en file **avant** que la console ne déclare sa
    recherche — ceux-là arrivent avec des réglages vides. Un run normal apporte
    les siens : voir `_config_du_run`.
    """
    return Config(name="banc", theme="sorties enfants")


def _config_du_run(run: dict[str, Any], quiet: bool) -> Config:
    """La configuration **que le run déclare**, et non celle qu'on fabriquerait.

    Le sens de la flèche compte. Avant, le worker inventait une fenêtre et la
    déclarait au site ; désormais c'est la console qui la fixe au lancement, en
    dates absolues, et le worker obéit.

    Deux choses y gagnent. D'abord ces valeurs servent **deux fois** — elles
    partent dans le prompt du tri, et elles servent à juger ce qu'il a rendu :
    venant du même endroit, elles ne peuvent plus se contredire. Ensuite un run
    devient rejouable à l'identique : une fenêtre relative aurait fait qu'un
    même run ne mesure plus la même chose selon le jour où on le rejoue.
    """
    recherche = run.get("recherche") or {}
    if not recherche:
        if not quiet:
            print(
                "  Run sans recherche déclarée — configuration de repli du banc.",
                flush=True,
            )
        return _fournisseur_du_run(_bench_config(), run, quiet)

    config = Config(
        name="banc",
        theme=str(recherche.get("theme") or "sorties enfants"),
        postal_prefixes=[str(p) for p in (recherche.get("postalPrefixes") or [])]
        or list(IDF_POSTAL_PREFIXES),
        max_links_per_agenda=int(recherche.get("maxLinks") or 8),
        # La fenêtre est absolue : `Config` la calcule d'ordinaire depuis
        # `horizon_days`, à partir d'aujourd'hui. On la lui impose.
        window=(str(recherche.get("dateFrom") or ""), str(recherche.get("dateTo") or "")),
    )
    return _fournisseur_du_run(config, run, quiet)


def _fournisseur_du_run(config: Config, run: dict[str, Any], quiet: bool) -> Config:
    """Par qui ce run est joué — ce que **le run déclare**, et rien d'autre.

    Même sens de flèche que pour la recherche, et pour la même raison : c'est
    la console qui décide sous quoi on mesure, pas la machine qui mesure. Deux
    runs lancés à dix minutes d'écart peuvent ainsi employer deux fournisseurs
    différents sans qu'on touche au service, ce qui est exactement la
    comparaison qu'un banc existe pour rendre possible.

    Un run mis en file avant ce changement ne porte pas la clé : il retombe
    alors sur le fournisseur de production, et c'est le bon défaut — il a été
    lancé quand c'était le seul.

    Le nom est validé ici plutôt qu'au premier appel : une valeur inattendue
    doit arrêter le run avant qu'il ne commence, pas au milieu du corpus.
    """
    demande = run.get("extraction") or {}
    if not isinstance(demande, dict):
        return config
    fournisseur = str(demande.get("provider") or "").strip().lower()
    if not fournisseur:
        return config
    if fournisseur not in PROVIDERS:
        raise ConfigError(
            f"fournisseur inconnu dans les réglages du run : « {fournisseur} » "
            f"(connus : {', '.join(PROVIDERS)})"
        )
    if not quiet:
        print(f"  Fournisseur déclaré par le run : {fournisseur}.", flush=True)
    modele = str(demande.get("model") or "").strip()

    if fournisseur == "openrouter":
        # Le modèle d'un run OpenRouter est celui de l'étage joué, pas un point
        # de contrôle à part : il part dans `select_model` **et**
        # `extraction_model`, puisqu'un run ne joue qu'un étage à la fois et
        # qu'on ne sait pas encore lequel ici.
        #
        # Vérifié tout de suite : `replace` ne repasse pas par `validated`, et
        # un slug fautif n'échouerait qu'à la première entrée du corpus — après
        # avoir occupé le worker et fait attendre les recherches derrière.
        resolu = modele or config.extraction_model
        try:
            modele_openrouter(resolu)
        except ProviderError as err:
            raise ConfigError(f"modèle du run : {err}") from err
        # L'effort de raisonnement se compare comme le modèle : c'est même la
        # comparaison la plus intéressante qu'on puisse faire sur ce
        # fournisseur, puisque passer de « rien demandé » à « low » a divisé le
        # coût d'une reconnaissance par seize. Validé ici, pour la même raison
        # que le modèle — `replace` ne repasse pas par `validated`.
        effort = str(demande.get("effort") or "").strip().lower()
        if effort and effort not in EFFORTS:
            raise ConfigError(
                f"effort de raisonnement inconnu dans les réglages du run : "
                f"« {effort} » (connus : {', '.join(EFFORTS)})"
            )
        return replace(
            config,
            provider=fournisseur,
            select_model=resolu,
            extraction_model=resolu,
            reasoning_effort=effort or config.reasoning_effort,
        )

    return replace(
        config,
        provider=fournisseur,
        gliner_model=modele or config.gliner_model,
    )


def _declare(stage: str, config: Config | None) -> dict[str, str]:
    """De quoi ce run est le run : le modèle interrogé, l'empreinte de son prompt.

    Déclaré **à la clôture**, et pas en réclamant le travail : le worker ne sait
    quel modèle il emploiera qu'une fois le run réclamé, puisque c'est l'étage
    qui le dit. Les deux colonnes restaient donc vides, et deux points d'une
    courbe n'étaient ni comparables ni distinguables — ce qui est irrattrapable
    après coup, un run joué ne disant jamais ce qu'il était.

    L'empreinte porte sur le **gabarit**, pas sur le prompt rendu : celui-ci
    change à chaque page, et ce qu'on veut savoir est si deux runs ont posé la
    même question.
    """
    if config is None:
        # Les deux étages de Python pur n'interrogent personne : annoncer un
        # modèle qu'ils n'ont pas appelé serait une déclaration fausse.
        return {"model": "", "promptHash": ""}
    prompt = config.select_prompt if stage == "SELECT" else config.extraction_prompt
    model = config.select_model if stage == "SELECT" else config.extraction_model
    if stage == "EXTRACT" and config.provider == "gliner":
        # Sans cette ligne, un run GLiNER se déclarerait joué par Haiku : deux
        # points de la courbe porteraient le même modèle, et la comparaison que
        # ce run existe pour rendre serait irrattrapable après coup.
        model = f"gliner:{config.gliner_model}"
    elif config.provider == "openrouter":
        # Le nom **résolu**, celui qu'on a réellement appelé : un run laissé au
        # défaut se déclarerait sinon joué par « claude-haiku-4-5 », qui n'a pas
        # joué ce run — c'est le modèle par défaut du routeur qui l'a fait. Deux
        # points de la courbe porteraient le même nom pour deux modèles
        # différents, et la comparaison serait perdue.
        #
        # L'effort de raisonnement en fait partie : deux runs du même modèle à
        # « low » et à « max » ne sont pas deux états d'une même chose, et le
        # second peut coûter seize fois le premier. Un nom qui les confondrait
        # rendrait la courbe illisible, et c'est irrattrapable après coup.
        model = modele_openrouter(model)
        if config.reasoning_effort:
            model = f"{model} ({config.reasoning_effort})"
    return {
        "model": model,
        "promptHash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
    }


def _code_ref() -> str:
    """La révision qui tourne, si le dépôt est là. Vide sinon, et c'est dit.

    Sans elle, un point de la courbe ne s'attribue à rien. On ne la devine pas :
    ou bien git répond, ou bien le run le déclare inconnu.
    """
    try:
        import subprocess

        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip()[:60] if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 — un dépôt absent n'est pas une panne
        return ""


#: Au-delà, une entrée de banc est réputée coincée et le worker **crache sa
#: pile** sur la sortie d'erreur, sans s'arrêter.
#:
#: Ce n'est pas un plafond, c'est un témoin. Un run de banc est muet par
#: construction — son `RunLog` n'a ni fichier ni console —, si bien qu'un worker
#: bloqué ne se distingue en rien d'un worker lent : même absence de sortie,
#: même processus vivant. La seule façon de trancher était de se connecter au
#: VPS et d'attacher un débogueur à un processus qui, souvent, avait déjà été
#: redémarré.
#:
#: Trois minutes laissent passer tout ce qui est honnête ici — un étiquetage de
#: page tient en quelques secondes, un appel de modèle en quelques dizaines —
#: et attrapent ce qui ne l'est pas. Le pire cas honnête du modèle, lui, est un
#: appel qui va au bout de ses reprises : il dumpera, et c'est très bien, parce
#: que la pile dira justement qu'on attend le SDK.
ENTREE_LENTE_S = 180.0

#: Après tant d'entrées **d'affilée** en échec, le run s'arrête.
#:
#: Ce seuil sépare deux choses que le banc confondait. Une page qui échoue est
#: une mesure : elle se range et le run continue, c'est tout l'intérêt de ne pas
#: s'arrêter au premier accident. Une **brique qui ne peut pas tourner** — la
#: bibliothèque d'un fournisseur absente du venv, une clé d'API refusée, un
#: point de contrôle introuvable — n'est pas une mesure : c'est la même faute
#: répétée, et la rejouer cent fois ne produit pas cent renseignements, elle en
#: produit zéro et enterre le seul qui compte.
#:
#: C'est arrivé au premier run GLiNER : `gliner` n'était pas dans le venv du
#: worker, les cent entrées du corpus ont rendu la même `ProviderError` en une
#: minute, et le run s'est **clos en DONE** avec un taux calculé sur cent
#: fiches vides. Rien, dans la console, ne le distinguait d'une mesure.
#:
#: Cinq plutôt qu'une : une page peut légitimement faire échouer un appel, deux
#: à la suite arrivent, cinq ne sont plus un accident.
ECHECS_CONSECUTIFS_MAX = 5


class _Temoin:
    """Le témoin d'entrée lente, et sa seule règle : ne jamais casser le run.

    `faulthandler` écrit sur un **descripteur de fichier**, pas sur un objet
    Python. Si `sys.stderr` n'en a pas — un flux remplacé par un harnais de
    test, un superviseur qui le détourne —, l'armement lève
    `io.UnsupportedOperation`. Un instrument qui met en échec ce qu'il observe
    est pire que pas d'instrument du tout : le run s'arrêtait à la première
    entrée, et le message parlait de `fileno`.

    On tente donc une fois. Si ça ne passe pas, le témoin se tait pour de bon
    et le run continue sans lui.
    """

    def __init__(self, seuil: float = ENTREE_LENTE_S):
        self.seuil = seuil
        self.possible = True

    def armer(self) -> None:
        if not self.possible:
            return
        try:
            faulthandler.dump_traceback_later(self.seuil, repeat=False)
        except Exception:  # noqa: BLE001 — un témoin muet vaut mieux qu'un run mort
            self.possible = False

    def desarmer(self) -> None:
        if not self.possible:
            return
        try:
            faulthandler.cancel_dump_traceback_later()
        except Exception:  # noqa: BLE001 — même raison, symétrique
            self.possible = False


class BriqueInerte(RuntimeError):
    """La brique ne peut pas tourner — inutile de lui soumettre le corpus entier.

    Distincte d'une `ApiError` ou d'un bug : ici le worker fonctionne, c'est ce
    qu'on lui demande de jouer qui n'existe pas sur cette machine. Le motif doit
    donc arriver **entier** dans la console, parce qu'il contient d'ordinaire la
    commande à taper.
    """


def play_run(run: dict[str, Any], api: SppApi, env: Environment, quiet: bool) -> None:
    """Joue un run du banc : une brique, sur tout le corpus gelé.

    Le worker ne télécharge rien ici. Chaque entrée arrive **avec son HTML**,
    tel que la capture l'a figé, et la brique est rejouée dessus. Un écart
    entre deux runs ne peut donc venir que du code — ce qui est toute la raison
    d'être d'un banc.

    Les étages 4 et 6 appellent le modèle et se paient ; les étages 3 et 5 sont
    du Python pur. Le coût est compté et rendu à la clôture, parce qu'une
    mesure dont on tait le prix passe pour gratuite.
    """
    run_id = int(run["id"])
    stage = str(run["stage"])
    if not quiet:
        titre = run.get("label") or "sans étiquette"
        print(f"▶ Banc — run #{run_id} · étage {stage} · « {titre} »", flush=True)

    provider = None
    config = None
    log = RunLog(None, verbose=False)
    if stage in ("SELECT", "EXTRACT"):
        # Celle que le run déclare. Le modèle recevra donc exactement la
        # fenêtre contre laquelle le site le jugera — elles viennent de la même
        # ligne en base, et ne peuvent pas diverger.
        config = _config_du_run(run, quiet)
        # `search=False` : un run de banc rejoue une brique sur un corpus gelé,
        # jamais l'étage 1. Sans ça, un run joué par OpenRouter réclamerait une
        # clé de moteur pour une recherche qu'il ne lancera pas.
        provider = get_provider(
            config,
            api_key=env.anthropic_key,
            serper_key=env.serper_key,
            openrouter_key=env.openrouter_key,
            search=False,
        )

    traites = 0
    temoin = _Temoin()
    echecs_suite = 0
    dernier_echec = ""
    status, error = "DONE", None
    try:
        # Les catégories du site partent dans le prompt d'extraction : le modèle
        # doit y choisir la sienne. Les lui refuser faisait compter faux, à
        # chaque fiche, un champ qu'on l'empêchait de remplir — et le banc
        # mesurait un appel qui n'existe pas en production. Un site injoignable
        # met donc le run en échec plutôt que de rendre une mesure fausse.
        categories = sorted(api.categories()) if stage == "EXTRACT" else []
        total = int(run.get("items") or 0)
        while not _stop:
            item = api.next_eval_item(run_id)
            if not item:
                break
            depart = time.monotonic()
            # Armé avant l'entrée, désarmé après : si celle-ci dépasse le
            # seuil, la pile part sur la sortie d'erreur — donc dans le journal
            # du service — et le travail continue. Une entrée lente le dit une
            # fois, elle ne noie pas le journal.
            temoin.armer()
            html = str(item.get("html") or "")
            if stage in ("HARVEST", "SELECT"):
                page_id = int(item["pageId"])
                url = str(item["url"])
                if stage == "HARVEST":
                    result = harvest_from_html(html, url)
                else:
                    result = select_from_html(
                        html, url, provider=provider, config=config, log=log
                    )
                result["pageId"] = page_id
                api.report_eval_links(run_id, result)
            elif stage == "READ":
                sortie_id = int(item["sortieId"])
                result = read_from_html(html, str(item["url"]), fetcher=Fetcher())
                result["sortieId"] = sortie_id
                # `url` est l'adresse *lue* — celle que l'échange de langue a
                # pu changer. Le site la range sous `readUrl` ; la clé `url`
                # n'a pas de place dans son schéma.
                result["readUrl"] = result.pop("url", "")
                api.report_eval_read(run_id, result)
            else:
                sortie_id = int(item["sortieId"])
                lecture = read_from_html(html, str(item["url"]), fetcher=Fetcher())
                result = extract_page(
                    str(item["url"]),
                    lecture.get("text", ""),
                    provider=provider,
                    config=config,
                    log=log,
                    categories=categories,
                    declared_dates=lecture.get("dates", []),
                    hints=lecture.get("facts") or {},
                )
                result["sortieId"] = sortie_id
                api.report_eval_extract(run_id, result)
            temoin.desarmer()
            traites += 1

            # Le relevé d'une entrée peut porter une erreur — le rejeu de la
            # brique a échoué sur cette page. On le range, on le dit, et on
            # compte : c'est la répétition qui distingue l'accident de la
            # panne.
            echec = str(result.get("error") or "")
            if echec:
                echecs_suite += 1
                dernier_echec = echec
                if not quiet:
                    print(f"  ✗ {echec}", flush=True)
                if echecs_suite >= ECHECS_CONSECUTIFS_MAX:
                    raise BriqueInerte(
                        f"{echecs_suite} entrées d'affilée en échec, toutes pour la même "
                        f"raison — la brique ne peut pas tourner : {dernier_echec}"
                    )
            else:
                echecs_suite = 0
            if not quiet:
                # Une ligne par entrée, et c'est le minimum : sans elle, un run
                # de deux cents pages est un écran vide pendant une heure, et
                # « il est bloqué » ne se distingue pas de « il travaille ».
                compte = f"{traites}/{total}" if total else str(traites)
                print(
                    f"  {compte} · {time.monotonic() - depart:.1f} s · {item.get('url', '')}",
                    flush=True,
                )
    except BriqueInerte as err:
        # Pas de trace : ce n'est pas un bug du worker, c'est une brique qu'on
        # lui a demandé de jouer sans lui en donner les moyens. Le motif part
        # dans la console, où il se lit sans ouvrir un journal.
        status, error = "FAILED", str(err)
    except ApiError as err:
        status, error = "FAILED", str(err)
    except Exception as err:  # noqa: BLE001 — la trace part dans la console du service
        traceback.print_exc()
        status, error = "FAILED", f"{err.__class__.__name__} : {err}"
    finally:
        # Un témoin armé survivrait au run et dumperait dans le vide, au milieu
        # du travail suivant.
        temoin.desarmer()
        usage = getattr(provider, "usage", None)
        payload: dict[str, Any] = {
            "items": traites,
            "inputTokens": int(getattr(usage, "input_tokens", 0) or 0),
            "outputTokens": int(getattr(usage, "output_tokens", 0) or 0),
            "costUsd": round(float(getattr(usage, "total_usd", 0.0) or 0.0), 4),
            **_declare(stage, config),
        }
        if error:
            payload["error"] = error
        try:
            api.finish_eval_run(run_id, status, **payload)
        except ApiError as err:
            print(f"Clôture impossible du run #{run_id} : {err}", file=sys.stderr, flush=True)
        if not quiet:
            fin = "terminé" if status == "DONE" else f"en échec ({error})"
            print(f"■ Banc — run #{run_id} {fin} — {traites} entrée(s), {payload['costUsd']} $", flush=True)



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sortiesbot.worker",
        description="Exécute les recherches mises en file depuis la console du site.",
    )
    parser.add_argument("--once", action="store_true", help="au plus une exécution, puis sortir")
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_SECONDS,
        help=f"secondes entre deux passages à vide (défaut : {POLL_SECONDS})",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="pas de sortie console")
    parser.add_argument(
        "--runs-dir",
        default=str(ROOT / "runs"),
        help="dossier des journaux de run (défaut : scraper/runs)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env")
    env = Environment.from_env()

    # Le worker soumet des sorties et écrit dans la mémoire partagée : sans
    # clé d'API il ne peut rien faire, autant le dire tout de suite.
    if not env.api_key:
        print("SPP_API_KEY est requis (voir .env.example)", file=sys.stderr)
        return 2
    # Un modèle, au moins : lequel dépend de la recherche qu'on lui donnera,
    # et le worker ne le sait pas en démarrant. Exiger la clé d'Anthropic
    # aurait fermé la porte à une installation qui ne tourne qu'au routeur ;
    # n'en exiger aucune l'ouvrirait à un service qui démarre pour échouer à
    # chaque exécution.
    if not env.anthropic_key and not env.openrouter_key:
        print(
            "Une clé de modèle est requise : ANTHROPIC_API_KEY, OPENROUTER_API_KEY, "
            "ou les deux (voir .env.example)",
            file=sys.stderr,
        )
        return 2

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    api = SppApi(env.api_url, env.api_key)
    runs_dir = Path(args.runs_dir)
    if not args.quiet:
        print(f"Worker en écoute sur {env.api_url} (toutes les {args.interval} s).", flush=True)

    while not _stop:
        try:
            job = api.next_run()
        except ApiError as err:
            # Site en cours de redéploiement, base indisponible : on réessaie.
            if not args.quiet:
                print(f"Site injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            job = None
        if job:
            execute(job, api, env, runs_dir, args.quiet)
            if args.once:
                return 0
            continue

        # Les recherches d'abord, le banc ensuite : une recherche produit des
        # sorties que des parents attendent, le banc attend un humain qui le
        # relira quand il pourra. À file égale, c'est la recherche qui passe.
        #
        # Et dans le banc, **capturer avant mesurer** : un run joué sur un
        # corpus incomplet mesure ce qu'on a sous la main, pas ce qu'on voulait
        # mesurer. Geler est en outre gratuit, là où un run des étages 4 et 6
        # se paie.
        try:
            job = api.next_capture()
        except ApiError as err:
            if not args.quiet:
                print(f"Banc injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            job = None
        if job:
            capture(job, api, args.quiet)
            if args.once:
                return 0
            continue

        # Les chasses avant les runs, pour la raison qui met déjà les captures
        # avant eux : elles construisent le corpus, et un run joué sur un
        # corpus incomplet mesure ce qu'on a sous la main plutôt que ce qu'on
        # voulait mesurer. Elles passent en revanche **après** les captures,
        # qui ne coûtent rien là où une chasse lance de vraies recherches.
        try:
            job = api.next_hunt(code_ref=_code_ref())
        except ApiError as err:
            if not args.quiet:
                print(f"Banc injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            job = None
        if job:
            chasse(job, api, env, args.quiet)
            if args.once:
                return 0
            continue

        try:
            # Le worker déclare **ce qu'il est** — sa révision —, plus ce qu'on
            # cherche : ça vient du run, fixé au lancement depuis la console.
            run = api.next_eval_run(code_ref=_code_ref())
        except ApiError as err:
            if not args.quiet:
                print(f"Banc injoignable ({err}) — nouvelle tentative.", file=sys.stderr, flush=True)
            run = None
        if run:
            play_run(run, api, env, args.quiet)
            if args.once:
                return 0
        elif args.once:
            if not args.quiet:
                print("Rien en file.", flush=True)
            return 0
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
