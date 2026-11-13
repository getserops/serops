---
seo_title: "Our open source promise"
description: "Every feature in SerOps Community stays in Community, under AGPL-3.0, forever. What Community includes, and what Enterprise adds."
---
# Our open source promise

**Effective 21 October 2026, updated 13 November 2026.** Every change to this page is public: see its
[history](https://github.com/getserops/serops/commits/main/docs/src/open-source-promise.md).
[Version française ci-dessous](#notre-engagement-open-source).

> **Every feature in SerOps Community stays in Community, under AGPL-3.0,
> forever. We will never move a Community feature to a paid tier, and never
> add limits on users, projects, services or data.**

SerOps comes in three forms:

- **Community**: the complete product, open source under the
  [AGPL-3.0](license.md), self-hosted, free.
- **Cloud** (planned for 2027): the same product, run by us.
- **Enterprise**: Community plus governance features for large
  organisations, under a commercial license, self-hosted with a license key or
  in a higher Cloud tier. The first Enterprise features, custom roles and
  per-project access, shipped in 1.3.0 (11 November 2026).

Enterprise only ever **adds**. Nothing below will be removed from Community,
restricted, or moved to Enterprise.

## What stays in Community, forever

Everything SerOps does as of **v1.2.4**, the last release before this page:

**Root cause analysis**

- Scheduled AI analysis of logs, metrics, traces, deployments and code
  changes per project and environment (every 15 minutes by default), and on
  incoming alerts
- Issues detected without any alert, with deduplication, mute, resolve,
  reopen and acknowledge
- Deployment correlation: incidents matched to when code reached each
  environment
- Kubernetes awareness (pods, restarts, OOMKills, per-service metrics) and
  plain VMs
- On-demand investigations of any time window
- AI chat on incidents
- Past-incident memory: similar resolved issues suggested as precedent;
  post-mortem drafts
- Timelines, dashboards and analysis history

**AI providers and cost**

- Anthropic Claude, Google Gemini, OpenAI, DeepSeek and any OpenAI-compatible
  provider, with your own key; local models through Ollama for fully
  on-premises analysis
- Sentinel: the AI call is skipped when nothing changed
- Duplicate errors collapsed, prompt caching, monthly AI budget per
  organisation, cost tracking
- Fallback, rate limiting and circuit breaker

**Integrations (all of them, and every future one)**

- Logs: Elasticsearch, OpenSearch, Loki, Splunk, Datadog, AWS CloudWatch,
  Google Cloud Logging, Azure Log Analytics
- Metrics: Prometheus, VictoriaMetrics, Grafana Mimir, Datadog, AWS
  CloudWatch, Google Cloud Monitoring, Azure Monitor
- Traces: built-in OTLP receiver, Jaeger, Zipkin, Grafana Tempo, Datadog APM
- Code and CI/CD: GitHub, GitLab, Bitbucket, Azure DevOps, Jenkins;
  deployments from Argo CD and Flux
- Alerts in: Alertmanager, Grafana, Datadog
- Notifications out: email, Slack, Microsoft Teams, PagerDuty, Opsgenie, with
  routing rules, escalation, quiet hours and digests

**Access and security**

- Multiple organisations per install, each isolated from the others
- Roles (admin, user, viewer) with named permissions checked on every request
- OpenID Connect single sign-on
- Audit log, including refused requests, with export
- API keys
- PII and secret redaction before anything reaches an AI provider
- Credentials encrypted in your own database
- Password reset and change with full session revocation; GDPR account and
  organisation deletion

**Operations**

- Docker Compose and Helm chart; multi-cluster and multi-region deployments
- Data retention controls
- Prometheus metrics for SerOps itself
- REST API, English and French interface

**Also in Community, always:**

- **Every baseline security feature, including future ones**, such as
  two-factor authentication, encryption-key rotation, encryption at rest and
  PII redaction.
- **Every integration**: logs, metrics, traces, source control, CI/CD,
  GitOps, alerts and notifications.
- **No limits** on users, projects, services or data.
- **SSO groups and teams** (from 1.3.0): map identity-provider groups to
  roles and teams, and group members into teams.
- **Enforced single sign-on and tamper-evident audit export**, when they
  ship: requiring every sign-in to go through your identity provider, and
  proving that an audit export was not altered. They protect one install,
  so they belong here.

## What Enterprise adds

New features only, for the governance needs of large organisations:

- Custom roles and per-project access (from 1.3.0)
- Planned: SAML 2.0 single sign-on
- Planned: SCIM provisioning (user and group sync)
- Planned: real-time streaming of audit events to a SIEM
- Planned: delegated administration across organisations
- Planned: compliance reports
- A commercial license (opt-out of AGPL copyleft) and contractual support,
  already offered

## How we decide

A new feature is **Enterprise only if it serves the governance needs of a
large organisation**: central identity, compliance, administration at scale.
If it serves security, reliability, or the root cause analysis itself, it is
**Community**.

## Questions

**Will features ever move from Community to Enterprise?** No.

**What happens if an Enterprise license expires?** Enterprise features switch
off. No data is deleted and every Community feature keeps working.

**Does Enterprise code phone home?** No. License keys are checked offline;
SerOps sends nothing to us. See [license](license.md#enterprise-code-ee-directories).

**Why write this down?** Earlier, our website said "every feature, no lite
tier". That was too absolute to stay true once paid features exist, so we
made it precise before any paid feature was built.

---

## Notre engagement open source

**En vigueur le 21 octobre 2026, mis à jour le 13 novembre 2026.** Chaque modification de cette page est
publique : voir son
[historique](https://github.com/getserops/serops/commits/main/docs/src/open-source-promise.md).

> **Toutes les fonctionnalités de SerOps Community restent dans Community,
> sous AGPL-3.0, pour toujours. Nous ne déplacerons jamais une fonctionnalité
> Community vers une offre payante, et n'ajouterons jamais de limite sur les
> utilisateurs, les projets, les services ou les données.**

SerOps existe sous trois formes :

- **Community** : le produit complet, open source sous
  [AGPL-3.0](license.md), auto-hébergé, gratuit.
- **Cloud** (prévu en 2027) : le même produit, opéré par nous.
- **Enterprise** : Community plus des fonctionnalités de gouvernance pour les
  grandes organisations, sous licence commerciale, auto-hébergé avec une clé
  de licence ou dans une offre Cloud supérieure. Les premières
  fonctionnalités Enterprise, rôles personnalisés et accès par projet,
  sont disponibles depuis la 1.3.0 (11 novembre 2026).

Enterprise ne fait qu'**ajouter**. Rien de ce qui suit ne sera retiré de
Community, restreint, ou déplacé vers Enterprise.

### Ce qui reste dans Community, pour toujours

Tout ce que fait SerOps en version **v1.2.4**, la dernière version publiée
avant cette page :

- **Analyse des causes** : analyse IA planifiée des logs, métriques, traces,
  déploiements et changements de code par projet et environnement (toutes les
  15 minutes par défaut) et sur alerte entrante ; détection d'incidents sans
  alerte, avec déduplication, mise en sourdine, résolution, réouverture et
  prise en compte ; corrélation avec les déploiements ; prise en charge de
  Kubernetes (pods, redémarrages, OOMKills, métriques par service) et des VM ;
  investigations à la demande ; chat IA sur les incidents ; mémoire des
  incidents passés et brouillons de post-mortem ; chronologies, tableaux de
  bord et historique des analyses.
- **Fournisseurs IA et coûts** : Anthropic Claude, Google Gemini, OpenAI,
  DeepSeek et tout fournisseur compatible OpenAI, avec votre propre clé ;
  modèles locaux via Ollama ; Sentinel ; regroupement des erreurs
  identiques, cache de prompt, budget IA mensuel par organisation, suivi des
  coûts ; repli, limitation de débit et disjoncteur.
- **Intégrations (toutes, et toutes les futures)** : logs (Elasticsearch,
  OpenSearch, Loki, Splunk, Datadog, AWS CloudWatch, Google Cloud Logging,
  Azure Log Analytics) ; métriques (Prometheus, VictoriaMetrics, Grafana
  Mimir, Datadog, AWS CloudWatch, Google Cloud Monitoring, Azure Monitor) ;
  traces (récepteur OTLP intégré, Jaeger, Zipkin, Grafana Tempo, Datadog APM) ;
  code et CI/CD (GitHub, GitLab, Bitbucket, Azure DevOps, Jenkins ;
  déploiements Argo CD et Flux) ; alertes entrantes (Alertmanager, Grafana,
  Datadog) ; notifications (e-mail, Slack, Microsoft Teams, PagerDuty,
  Opsgenie) avec règles de routage, escalade, heures calmes et résumés.
- **Accès et sécurité** : plusieurs organisations isolées par installation ;
  rôles (admin, utilisateur, lecteur) avec permissions nommées vérifiées à
  chaque requête ; SSO OpenID Connect ; journal d'audit, y compris les
  requêtes refusées, avec export ; clés d'API ; masquage des données
  personnelles et des secrets avant tout envoi à un fournisseur IA ;
  identifiants chiffrés dans votre base ; réinitialisation et changement de
  mot de passe avec révocation des sessions ; suppression RGPD des comptes et
  des organisations.
- **Exploitation** : Docker Compose et chart Helm ; déploiements
  multi-clusters et multi-régions ; contrôle de la rétention des données ;
  métriques Prometheus de SerOps ; API REST, interface en anglais et en
  français.

**Toujours dans Community également :**

- **Toutes les fonctionnalités de sécurité de base, y compris les futures**,
  comme l'authentification à deux facteurs, la rotation des clés de
  chiffrement, le chiffrement au repos et le masquage des données
  personnelles.
- **Toutes les intégrations** : logs, métriques, traces, gestion de code,
  CI/CD, GitOps, alertes et notifications.
- **Aucune limite** sur les utilisateurs, les projets, les services ou les
  données.
- **Groupes SSO et équipes** (à partir de 1.3.0) : associer les groupes du
  fournisseur d'identité aux rôles et aux équipes, et regrouper les membres
  en équipes.
- **SSO imposé et export d'audit infalsifiable**, dès leur sortie : exiger
  que chaque connexion passe par votre fournisseur d'identité, et prouver
  qu'un export d'audit n'a pas été modifié. Ils protègent une installation,
  ils ont donc leur place ici.

### Ce qu'Enterprise ajoute

Uniquement de nouvelles fonctionnalités, pour les besoins de gouvernance des
grandes organisations :

- Rôles personnalisés et accès par projet (à partir de 1.3.0)
- Prévu : SSO SAML 2.0
- Prévu : provisionnement SCIM (synchronisation des utilisateurs et des groupes)
- Prévu : envoi en temps réel des événements d'audit vers un SIEM
- Prévu : administration déléguée entre organisations
- Prévu : rapports de conformité
- Une licence commerciale (sans les obligations copyleft de l'AGPL) et un
  support contractuel, déjà proposés

### Comment nous décidons

Une nouvelle fonctionnalité est **Enterprise uniquement si elle répond aux
besoins de gouvernance d'une grande organisation** : identité centralisée,
conformité, administration à grande échelle. Si elle sert la sécurité, la
fiabilité ou l'analyse des causes elle-même, elle est **Community**.

### Questions

**Des fonctionnalités passeront-elles un jour de Community à Enterprise ?**
Non.

**Que se passe-t-il quand une licence Enterprise expire ?** Les
fonctionnalités Enterprise se désactivent. Aucune donnée n'est supprimée et
toutes les fonctionnalités Community continuent de fonctionner.

**Le code Enterprise contacte-t-il nos serveurs ?** Non. Les clés de licence
sont vérifiées hors ligne ; SerOps ne nous envoie rien.

**Pourquoi l'écrire ?** Notre site disait auparavant « toutes les
fonctionnalités, pas de version allégée ». C'était trop absolu pour rester
vrai une fois des fonctionnalités payantes ajoutées : nous l'avons précisé
avant qu'aucune fonctionnalité payante n'existe.
