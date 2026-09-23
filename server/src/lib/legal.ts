/**
 * Les pages légales, écrites **une fois**.
 *
 * Elles s'affichent à deux endroits : dans le document pré-rendu que le
 * serveur envoie, et dans la vue Vue qui le remplace une fois l'application
 * démarrée. Deux copies d'un texte juridique finiraient par diverger — on
 * corrigerait l'une, jamais l'autre —, et la page mentirait alors à la moitié
 * de ses lecteurs. Le texte vit donc ici, en données ; le serveur le rend en
 * HTML et le sert aussi par l'API, où la vue le relit (voir
 * `client/src/lib/etatInitial.ts` : au premier affichage, ce n'est même pas
 * un appel réseau).
 *
 * Rien ici n'est du HTML. Ce sont des chaînes, échappées au rendu : une page
 * légale n'a aucune raison de pouvoir injecter quoi que ce soit.
 */

export interface SectionLegale {
  titre: string;
  paragraphes: string[];
  /**
   * Un geste que la vue propose à la suite du texte. Seule l'application peut
   * le rendre — le document pré-rendu, lui, n'a pas de JavaScript à offrir —,
   * et c'est pourquoi le texte qui l'accompagne doit se suffire sans lui.
   */
  action?: 'opposition-audience';
}

export interface PageLegale {
  slug: string;
  chemin: string;
  titre: string;
  description: string;
  sections: SectionLegale[];
}

const EDITEUR = 'Florian Tanay';
const CONTACT = 'floriantanay@gmail.com';

/**
 * L'hébergeur, dont la loi impose de publier les coordonnées.
 *
 * Le téléphone y figure parce que l'article 6 III de la LCEN le réclame au
 * même titre que l'adresse — c'est une des rares mentions dont l'absence se
 * remarque, puisqu'elle prive le lecteur du seul moyen de joindre quelqu'un
 * quand l'éditeur ne répond plus.
 */
const HEBERGEUR =
  'OVH SAS, 2 rue Kellermann, 59100 Roubaix, France — téléphone : 1007 — https://www.ovhcloud.com';

const mentionsLegales: PageLegale = {
  slug: 'mentions-legales',
  chemin: '/mentions-legales',
  titre: 'Mentions légales',
  description: "Éditeur, directeur de la publication et hébergeur du site SortiesPourPetits.",
  sections: [
    {
      titre: 'Éditeur du site',
      paragraphes: [
        `Ce site est édité par ${EDITEUR}, particulier, à titre non professionnel et sans but lucratif.`,
        `Contact : ${CONTACT}`,
        "Conformément à l'article 6 III 2 de la loi pour la confiance dans l'économie numérique, un particulier qui édite un site à titre non professionnel peut ne pas publier son adresse personnelle, à condition d'avoir communiqué son identité à son hébergeur. C'est le cas ici : les coordonnées de l'hébergeur figurent ci-dessous, et il détient l'identité de l'éditeur.",
      ],
    },
    {
      titre: 'Directeur de la publication',
      paragraphes: [EDITEUR],
    },
    {
      titre: 'Hébergeur',
      paragraphes: [HEBERGEUR, 'Le site et ses données sont hébergés en France.'],
    },
    {
      titre: 'Contenus proposés par les visiteurs',
      paragraphes: [
        "Les sorties publiées proviennent de propositions de visiteurs ou d'une recherche automatique sur des sites publics. Chacune passe par une modération avant d'être visible, mais cette relecture ne garantit ni l'exactitude des informations, ni la tenue effective des événements annoncés. Vérifiez auprès de l'organisateur avant de vous déplacer.",
        `Si un contenu vous paraît inexact, contrefaisant ou déplacé, signalez-le à ${CONTACT} : il sera examiné et, le cas échéant, retiré.`,
      ],
    },
    {
      titre: 'Propriété intellectuelle',
      paragraphes: [
        "Les textes et photographies proposés par les visiteurs restent la propriété de leurs auteurs, qui en autorisent la publication sur ce site en les soumettant. Les données cartographiques proviennent d'OpenStreetMap et de ses contributeurs, sous licence ODbL.",
      ],
    },
    {
      titre: 'Liens vers des sites tiers',
      paragraphes: [
        "Chaque sortie renvoie vers le site de son organisateur. Ces sites sont indépendants de SortiesPourPetits, qui n'a aucun contrôle sur leur contenu ni sur la façon dont ils traitent vos données.",
      ],
    },
  ],
};

const confidentialite: PageLegale = {
  slug: 'confidentialite',
  chemin: '/confidentialite',
  titre: 'Politique de confidentialité',
  description:
    'Quelles données ce site collecte, pourquoi, combien de temps, et comment exercer vos droits.',
  sections: [
    {
      titre: 'Responsable du traitement',
      paragraphes: [
        `${EDITEUR}, éditeur du site, est responsable des traitements décrits ci-dessous. Pour toute question ou pour exercer vos droits : ${CONTACT}`,
      ],
    },
    {
      titre: 'Consulter le site sans compte',
      paragraphes: [
        "Parcourir les sorties ne demande aucun compte et ne dépose aucun cookie. Seule la mesure d'audience décrite plus bas enregistre quelque chose, et elle ne vous identifie pas.",
      ],
    },
    {
      titre: 'Compte et cookie de session',
      paragraphes: [
        "Créer un compte enregistre votre adresse électronique, le nom que vous choisissez d'afficher et votre mot de passe, qui n'est jamais conservé en clair mais sous forme d'empreinte chiffrée. Ces données servent à vous authentifier et à rattacher les sorties que vous proposez.",
        "La connexion dépose un cookie de session d'une durée de sept jours. Il est strictement nécessaire au fonctionnement du service : sans lui, vous ne pourriez pas rester connecté. À ce titre il ne requiert pas votre consentement, et il disparaît à la déconnexion.",
        "Base légale : l'exécution du service que vous demandez en créant un compte.",
      ],
    },
    {
      titre: 'Sorties que vous proposez',
      paragraphes: [
        "Le titre, la description, les dates, le lieu et la photographie d'une sortie que vous proposez deviennent publics une fois la proposition approuvée par la modération. Votre nom d'affichage est associé à la proposition pour les modérateurs ; votre adresse électronique ne l'est jamais publiquement.",
      ],
    },
    {
      titre: 'Recherche d’adresse',
      paragraphes: [
        "Quand vous saisissez l'adresse d'un lieu dans le formulaire de proposition, votre navigateur interroge directement le service de géocodage Photon, opéré par komoot en Allemagne, pour proposer des adresses correspondantes. Ce service reçoit donc le texte que vous tapez et l'adresse IP de votre navigateur. Il n'est sollicité que sur ce formulaire, jamais pendant la simple consultation du site.",
      ],
    },
    {
      titre: "Mesure d'audience",
      paragraphes: [
        "Le site mesure sa fréquentation avec Umami, un logiciel libre installé sur le même serveur que le site, en France. Aucune donnée ne part chez un tiers.",
        "Cette mesure ne dépose aucun cookie et ne construit aucun identifiant qui vous suivrait d'une visite à l'autre ou d'un site à l'autre. Elle enregistre la page consultée, la page qui vous y a amené, la langue et la taille d'écran de votre navigateur, un pays déduit de l'adresse IP — l'adresse elle-même n'est pas conservée —, et les clics sur les liens qui mènent au site d'un organisateur.",
        "Ces informations servent uniquement à savoir quelles pages sont utiles et si le site remplit son rôle. Elles ne sont ni recoupées avec les comptes, ni transmises, ni vendues.",
        "Vous pouvez vous y opposer de deux façons : en activant l'option « Do Not Track » de votre navigateur, que cette mesure respecte, ou avec le bouton ci-dessous, qui enregistre votre refus dans votre navigateur. Ce refus vaut pour ce navigateur et cet appareil ; il est à renouveler ailleurs, et il disparaît si vous effacez les données du site.",
      ],
      action: 'opposition-audience',
    },
    {
      titre: 'Qui reçoit ces données',
      paragraphes: [
        "Personne d'autre que l'éditeur. Le site est hébergé par OVH, qui agit comme sous-traitant technique et n'exploite pas ces données pour son compte. Il n'y a ni régie publicitaire, ni outil d'analyse tiers, ni revente.",
        "Les deux seules exceptions sont décrites plus haut, et vous en êtes l'origine : la recherche d'adresse, qui interroge komoot, et les liens vers les sites d'organisateurs, que vous suivez de votre plein gré.",
      ],
    },
    {
      titre: 'Combien de temps',
      paragraphes: [
        "Les données de compte sont conservées tant que le compte existe, et effacées à sa suppression. Les sorties approuvées restent publiées tant qu'elles sont pertinentes. Les mesures d'audience sont conservées sous forme agrégée et ne permettent pas de remonter à une personne.",
      ],
    },
    {
      titre: 'Vos droits',
      paragraphes: [
        "Vous disposez d'un droit d'accès, de rectification, d'effacement, de limitation et d'opposition sur les données qui vous concernent, ainsi que d'un droit à la portabilité. Écrivez à " +
          CONTACT +
          ' : la demande est traitée dans un délai d’un mois.',
        "Si la réponse ne vous satisfait pas, vous pouvez saisir la Commission nationale de l'informatique et des libertés (CNIL), 3 place de Fontenoy, 75007 Paris — https://www.cnil.fr",
      ],
    },
  ],
};

export const PAGES_LEGALES: PageLegale[] = [mentionsLegales, confidentialite];

/** La page légale portant ce slug, ou `undefined`. */
export function pageLegale(slug: string): PageLegale | undefined {
  return PAGES_LEGALES.find((p) => p.slug === slug);
}

/** La page légale servie à ce chemin, ou `undefined`. */
export function pageLegaleParChemin(pathname: string): PageLegale | undefined {
  const normalise = pathname.replace(/\/+$/, '') || '/';
  return PAGES_LEGALES.find((p) => p.chemin === normalise);
}
