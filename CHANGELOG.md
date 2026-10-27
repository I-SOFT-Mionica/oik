# Changelog

Све значајне измене у овом пројекту се аутоматски бележе у овом фајлу од верзије 0.5.0 (semantic-release анализом коммит порука).

Формат: [Keep a Changelog](https://keepachangelog.com/sr/1.1.0/), верзионисање по [SemVer](https://semver.org/lang/sr/).

## <small>0.103.1 (2026-10-27)</small>

* fix(build): build installers on Python 3.14 (patched ssl), not 3.12.10 ([3cc1fee](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/3cc1fee))

## 0.103.0 (2026-10-27)

* feat(updates): run only installers that match a signed release manifest ([0f93bad](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/0f93bad))

## <small>0.102.1 (2026-10-27)</small>

* fix(gui): no more windows flashing when the app starts ([e4773d7](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/e4773d7))

## 0.102.0 (2026-10-27)

* feat(izmene): same bottom bar as Решења — folder, Освежи провере, Покрени ([ba875aa](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/ba875aa))

## 0.101.0 (2026-10-27)

* feat(izmene): permanent "Извези решења…" button in Измене ([5fadfd7](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/5fadfd7))

## 0.100.0 (2026-10-17)

* feat(phone): phone numbers are cleaned up wherever they come in ([986eaa8](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/986eaa8))

## <small>0.99.1 (2026-10-17)</small>

* fix(demo): demo and sample people use invented data that can't be anyone's ([9adc28a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/9adc28a))
* chore: publish_public handles long Windows paths ([2efb743](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/2efb743))
* chore: tooling to publish the code to the public GPL-3.0 repo ([31d41d8](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/31d41d8))

## 0.99.0 (2026-10-15)

* feat(licensing): verify licence signatures offline (Ed25519) ([6b347be](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/6b347be))

## <small>0.98.1 (2026-10-15)</small>

* fix(docs): user manual rewritten to match the app (file and in-app) ([c2c363b](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/c2c363b))
* ci: start release.yml explicitly after semantic-release tags a version ([2e137fd](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/2e137fd))

## 0.98.0 (2026-10-15)

* feat: keep hand-edited decisions, single running copy, clear JMBG clash message ([39348a1](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/39348a1))
* ci: semantic-release pushes tags with the org GitHub App token ([7658227](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/7658227))

## 0.97.0 (2026-10-15)

* feat(tour): guided spotlight tour with sample data for demo users ([c443805](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/c443805))

## 0.96.0 (2026-10-15)

* feat(commission): city and city-municipality commissions (ГИК, ИК ГО) ([4463208](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/4463208))

## <small>0.95.1 (2026-10-15)</small>

* perf: decouple decision-field and spacing edits from app-wide cascades ([93aba1f](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/93aba1f))

## 0.95.0 (2026-10-15)

* feat(onboarding): wizard covers everything, no trip to Поставке ИК needed ([fd84872](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/fd84872))

## <small>0.94.4 (2026-10-15)</small>

* ui: rename "Поставке ОИК" to "Поставке ИК" across the interface ([51383ce](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/51383ce))

## <small>0.94.3 (2026-10-15)</small>

* fix(ui): blank Пре/После spin boxes in CI builds (PySide6 6.12 layout regression) ([2a1b687](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/2a1b687))

## <small>0.94.2 (2026-10-15)</small>

* fix(perf): stop rebuilding full xlsx export on every signal, just to toggle a button ([ad7d41a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/ad7d41a))

## 0.94.0 (2026-10-15)

* feat(corrections): dated status-report export from Статус panel ([d7b180a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/d7b180a))

## <small>0.93.1 (2026-10-15)</small>

* fix(nacelnik): regenerate chief's template fresh + consistent Cyrillic headers ([9455223](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/9455223))

## 0.93.0 (2026-10-15)

* feat(corrections): surface cross-workflow JMBG conflicts in Конфликти ([15ffd3c](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/15ffd3c))

## <small>0.92.8 (2026-10-15)</small>

* fix(gui): debounce spacing-bar saves to stop reentrant preview rebuilds ([30e83cb](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/30e83cb))

## <small>0.92.7 (2026-10-14)</small>

* fix(gui): replace QDoubleSpinBox in spacing bar to fix blank fields in frozen build ([f243df1](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/f243df1))

## <small>0.92.6 (2026-10-13)</small>

* fix(phase3): exclude election day from "dana pre izbora" day count ([cfdb95a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/cfdb95a))

## <small>0.92.5 (2026-10-13)</small>

* fix(prosireni): normalize stale "Заменик клана" typo at parse/cache time ([9d57519](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/9d57519))

## <small>0.92.4 (2026-10-13)</small>

* fix(updates): clean up stale installer temp downloads before retrying ([b13da3f](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/b13da3f))

## <small>0.92.3 (2026-10-13)</small>

* fix(tests): drain Qt's deferred-delete queue with a real event loop, not processEvents() ([55c7e71](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/55c7e71))

## <small>0.92.2 (2026-10-13)</small>

* fix(tests): drain the Qt event queue after every test, not just once at session end ([a05ab3c](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/a05ab3c))
* ci(tests): run the Qt test suite offscreen to match local development ([8314a2f](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/8314a2f))

## <small>0.92.1 (2026-10-13)</small>

* fix(resenja): tie the preview's deferred scroll to the widget's own lifetime ([aff4cc3](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/aff4cc3))

## 0.92.0 (2026-10-12)

* fix(nacelnik): bring the chief's takeover template in line with the party-submission template ([76ec1a5](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/76ec1a5))
* feat(resenja): paginated page-accurate preview with anchor navigation, operator-configurable title/b ([ce7adf4](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/ce7adf4))

## 0.91.0 (2026-10-12)

* feat(resenja): fix "ЗА ИЗБОРА ЗА" grammar, make line spacing/header/footer operator-configurable ([5da0059](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/5da0059))
* fix(prosireni): correct "Заменик клана" typo baked into role labels since the first commit ([4885417](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/4885417))

## <small>0.90.2 (2026-10-12)</small>

* fix(gui): three live-testing bugs — button clipping, quota paint timing, broken reset-to-default ([7105f65](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/7105f65))

## <small>0.90.1 (2026-10-10)</small>

* fix(ci): the upload-trigger step's bash-style line continuation breaks under pwsh ([0d264aa](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/0d264aa))

## 0.90.0 (2026-10-10)

* fix(cross-workflow): surface duplicate JMBG as a correction instead of silently stripping it ([da67039](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/da67039))
* fix(date-picker): ignore mouse-wheel scroll to prevent accidental date changes ([abbf31e](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/abbf31e))
* fix(i18n): correct mixed Latin/Cyrillic typos, translate new strings ([4b39a7c](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/4b39a7c))
* feat(resenja): unify чл.15 Престанак into Измене, add shared delegated-signer option, fix Phase 3 pr ([0843fc1](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/0843fc1))
* refactor(obrazlozenje): move seed legal text from Python literals to bundled JSON resources ([700e83a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/700e83a))

## <small>0.89.1 (2026-10-05)</small>

* fix(declension): normalize place-name casing before declining ([917731f](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/917731f))
* fix(izmene): replace the authorization-date free-text field with a date picker ([f932c46](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/f932c46))

## 0.89.0 (2026-10-05)

* fix(oik): restore a visible, editable polling-station full name ([774bbf3](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/774bbf3))
* feat(phase1): merge Име/Презиме into one real input field ([08fcbb8](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/08fcbb8))

## <small>0.88.3 (2026-10-01)</small>

* fix(rik-import): stop erasing saved BM names/addresses on re-import ([e9ff1a5](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/e9ff1a5))

## <small>0.88.2 (2026-10-01)</small>

* fix(phase1): fix crash generating 6+ party files in parallel ([17a364a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/17a364a))

## <small>0.88.1 (2026-09-30)</small>

* fix(rik-import): backfill a party's blank full name on re-import ([29b033a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/29b033a))

## 0.88.0 (2026-09-30)

* feat(prosireni): give lists their own persistent contact info for Send ([79b1148](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/79b1148))
* fix(rik-import): handle the 2026 RASPODELA/legend export shape ([6914b3e](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/6914b3e))

## 0.87.0 (2026-09-29)

* feat(formalizator): open the destination folder from the save-as-PDF confirmation ([ddabbc7](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/ddabbc7))
* fix(formalizator): stop the fill-out screen's action buttons from clipping text ([e550255](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/e550255))

## <small>0.86.1 (2026-09-29)</small>

* fix(formalizator): shrink long values to fit their box instead of overflowing ([c84877d](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/c84877d))

## 0.86.0 (2026-09-29)

* feat(formalizator): explicit "Сачувај као PDF" printer choice ([9b2c586](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/9b2c586))

## 0.85.0 (2026-09-28)

* feat(formalizator): fill and print many declarations at once from Excel/CSV ([274cf82](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/274cf82))

## <small>0.84.6 (2026-09-24)</small>

* fix(app_state): files_dir() falls back to Documents instead of raising ([e64d9f3](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/e64d9f3))

## <small>0.84.5 (2026-09-24)</small>

* fix(phase1): Пошаљи stays enabled across restarts, and export_generated never raises ([730e447](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/730e447))
* chore: untrack Celik/ and temp/, and ignore them so it cannot recur ([5e83181](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/5e83181))

## <small>0.84.4 (2026-09-24)</small>

* fix(ux): confirm which folder was opened, and record the server fix as shipped ([cee38ca](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/cee38ca))

## <small>0.84.3 (2026-09-24)</small>

* fix(phase1): let "Отвори фасциклу" work before the first run ([8a5cfda](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/8a5cfda))
* docs: fold the server admin's findings into the Formalizator handoff [skip ci] ([d8fce49](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/d8fce49))

## <small>0.84.2 (2026-09-24)</small>

* fix(izbori): say what the РИК decision gate actually wants ([78d4a9f](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/78d4a9f))
* docs: handoff for the server admin on serving the Formalizator installer [skip ci] ([2ebac93](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/2ebac93))
* docs: record why releases need manual dispatch, and what to fix when there is time [skip ci] ([ccdf9a7](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/ccdf9a7))

## <small>0.84.1 (2026-09-24)</small>

* fix(i18n): translate every remaining string, and stop tests deleting real registry keys ([cd3b087](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/cd3b087))

## 0.84.0 (2026-09-24)

* docs: close TODO section 24, record the server-side open questions, run lupdate ([2f231cd](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/2f231cd))
* feat(alati): add a Formalizator tab that starts or installs the companion app ([1a22af2](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/1a22af2))
* feat(prosireni): open the section without waiting on electoral lists ([c5aa6e3](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/c5aa6e3))
* fix(updates): verify TLS against certifi so the download stops failing ([5739e4e](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/5739e4e))

## 0.83.0 (2026-09-12)

* feat(formalizator): let the operator pick the printer for the session ([9b9bb66](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/9b9bb66))

## <small>0.82.4 (2026-09-12)</small>

* fix(formalizator): print on machines with no default printer set ([93e3e8a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/93e3e8a))

## <small>0.82.3 (2026-09-12)</small>

* fix(formalizator): drop the printto verb entirely and stop falling back into it ([b159815](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/b159815))

## <small>0.82.2 (2026-09-12)</small>

* docs: add Formalizator roadmap ([ef795b5](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/ef795b5))
* fix(formalizator): fit scaled laptop screens, and validate JMBG properly ([f225519](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/f225519))
* fix(formalizator): let the uninstaller remove itself and its folder ([cc8ce31](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/cc8ce31))
* fix(formalizator): print through Qt instead of the shell printto verb ([e31d4ec](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/e31d4ec))

## <small>0.82.1 (2026-09-11)</small>

* fix(formalizator): never lose an entry when printing fails; route around virtual printers ([55b67e9](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/55b67e9))

## 0.82.0 (2026-09-11)

* feat(formalizator): bundle newly-calibrated NPRS-3/NPRS-4 forms ([f43db25](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/f43db25))

## 0.81.0 (2026-09-11)

* fix(ci): pass the built tag to upload-release.yml explicitly ([dcf3092](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/dcf3092))
* chore(formalizator): remove bundled starter forms (blank slate before rebuild) ([4cd151a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/4cd151a))
* feat(formalizator): default field content, page-ordered fields, custom-field management ([50a630c](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/50a630c))

## <small>0.80.2 (2026-09-11)</small>

* fix(formalizator): launch maximized; trim build size; group name headers ([ef64ffa](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/ef64ffa))

## <small>0.80.1 (2026-09-10)</small>

* fix(formalizator): remove all personal data on uninstall and on exit ([4863764](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/4863764))

## 0.80.0 (2026-09-10)

* feat(formalizator): voter-support signature collection companion app ([b155c1a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/b155c1a))

## 0.79.0 (2026-09-09)

* fix: also re-pin conventional-changelog-conventionalcommits under v6 ([dcaebd3](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/dcaebd3))
* fix: pin semantic-release extra_plugins to known-good versions ([b33ed7f](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/b33ed7f))
* fix: pin semantic-release's Node version instead of floating lts/* ([86d8cca](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/86d8cca))
* fix: upgrade cycjimmy/semantic-release-action v4 -> v6 ([5fc08c9](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/5fc08c9))
* feat: consume RIK's own multi-municipality RASPODELA/UKUPNO exports directly ([692a5aa](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/692a5aa))

## [0.78.3](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.78.2...v0.78.3) (2026-08-03)

## [0.78.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.78.1...v0.78.2) (2026-08-03)

## [0.78.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.78.0...v0.78.1) (2026-08-03)

## [0.78.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.77.3...v0.78.0) (2026-08-03)

## [0.77.3](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.77.2...v0.77.3) (2026-08-01)

## [0.77.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.77.1...v0.77.2) (2026-07-31)

## [0.77.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.77.0...v0.77.1) (2026-07-30)

## [0.77.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.76.3...v0.77.0) (2026-07-30)

## [0.76.3](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.76.2...v0.76.3) (2026-07-30)

## [0.76.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.76.1...v0.76.2) (2026-07-30)

## [0.76.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.76.0...v0.76.1) (2026-07-29)

## [0.76.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.75.1...v0.76.0) (2026-07-29)

## [0.75.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.75.0...v0.75.1) (2026-07-28)

## [0.75.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.74.0...v0.75.0) (2026-07-28)

## [0.74.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.73.1...v0.74.0) (2026-07-28)

## [0.73.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.73.0...v0.73.1) (2026-07-28)

## [0.73.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.72.2...v0.73.0) (2026-07-17)

## [0.72.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.72.1...v0.72.2) (2026-07-16)

## [0.72.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.72.0...v0.72.1) (2026-07-15)

## [0.72.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.71.0...v0.72.0) (2026-07-14)

## [0.71.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.70.0...v0.71.0) (2026-07-13)

## [0.70.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.69.0...v0.70.0) (2026-07-12)

## [0.69.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.68.0...v0.69.0) (2026-07-12)

## [0.68.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.67.2...v0.68.0) (2026-07-12)

## [0.67.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.67.1...v0.67.2) (2026-07-11)

## [0.67.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.67.0...v0.67.1) (2026-07-09)

## [0.67.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.66.0...v0.67.0) (2026-07-09)

## [0.66.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.65.0...v0.66.0) (2026-07-09)

## [0.64.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.64.0...v0.64.1) (2026-07-08)

## [0.62.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.62.1...v0.62.2) (2026-07-08)

## [0.62.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.62.0...v0.62.1) (2026-07-08)

## [0.61.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.60.1...v0.61.0) (2026-07-07)

## [0.60.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.60.0...v0.60.1) (2026-07-05)

## [0.60.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.59.0...v0.60.0) (2026-07-05)

## [0.59.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.58.0...v0.59.0) (2026-07-05)

## [0.58.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.57.1...v0.58.0) (2026-07-05)

## [0.57.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.57.0...v0.57.1) (2026-07-05)

## [0.57.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.56.0...v0.57.0) (2026-07-05)

## [0.56.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.55.0...v0.56.0) (2026-07-04)

## [0.55.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.54.1...v0.55.0) (2026-07-04)

## [0.54.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.54.0...v0.54.1) (2026-07-04)

## [0.54.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.53.0...v0.54.0) (2026-07-04)

## [0.53.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.52.0...v0.53.0) (2026-07-04)

## [0.52.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.51.0...v0.52.0) (2026-07-03)

## [0.51.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.50.0...v0.51.0) (2026-07-02)

## [0.50.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.49.0...v0.50.0) (2026-07-01)

## [0.49.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.48.0...v0.49.0) (2026-07-01)

## [0.48.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.47.1...v0.48.0) (2026-07-01)

## [0.47.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.47.0...v0.47.1) (2026-07-01)

## [0.47.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.46.0...v0.47.0) (2026-07-01)

## [0.46.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.45.2...v0.46.0) (2026-07-01)

## [0.45.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.45.1...v0.45.2) (2026-07-01)

## [0.45.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.45.0...v0.45.1) (2026-06-30)

## [0.45.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.44.0...v0.45.0) (2026-06-27)

## [0.44.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.43.0...v0.44.0) (2026-06-27)

## [0.43.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.42.1...v0.43.0) (2026-06-24)

### Додато

* **settings:** dynamic cutoff day labels + structured RIK decision fields ([956df66](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/956df6642a57e770ef5a77342733b82c7926de06))

## [0.42.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.42.0...v0.42.1) (2026-06-24)

### Поправљено

* **prosireni:** rename inbox import button label + add any_inbox_available guard ([5b323a3](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/5b323a36da9bddc1171cb8d992ce49207c8b3b80))

## [0.42.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.41.2...v0.42.0) (2026-06-24)

### Додато

* **gui:** restore phase buttons from log on startup + new election cycle ([48744fe](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/48744fe916c81db8d65fde38921c3e026f670699))

## [0.41.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.41.1...v0.41.2) (2026-06-24)

### Поправљено

* **prosireni:** full import pipeline + cache update + QMessageBox stubs ([f6efb24](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/f6efb24e7436d0de7ef03db3f9f956f26f7891ea))
* **thunderbird:** encode body commas as %2C instead of single-quoting ([a93c629](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/a93c6296ca352ed3a29989cf60ea85d74e329a4a))

## [0.41.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.41.0...v0.41.1) (2026-06-24)

### Поправљено

* **prosireni:** correct import_file arg order in _ProsireniPhase2Tab._import_files ([f6baf68](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/f6baf684f709385ab5b62b8ac1fddc90db3fbb5f))

## [0.41.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.40.1...v0.41.0) (2026-06-15)

### Додато

* **izmene:** generation_log + tab gating + auto-izmena on corrections save ([57be9fe](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/57be9fe56a8b6c68fb5d4d7d10a8a05218996680))

## [0.40.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.40.0...v0.40.1) (2026-06-15)

### Поправљено

* **prosireni:** rename entiteti→liste, fix start_worker call, add send button + tests ([e1e0ccb](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/e1e0ccb29cbeb7beb382f85782b5eca546697d65))

## [0.40.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.39.4...v0.40.0) (2026-06-14)

### Додато

* **gui:** prosireni corrections tab + label cleanup + Thunderbird per-user detection ([d8fa107](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/d8fa107d4cc98861a80962c64de4695157b2f45d))

## [0.39.4](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.39.3...v0.39.4) (2026-06-14)

### Поправљено

* **build:** disable UPX in all PyInstaller specs + fix upload workflow repo flag ([77b1852](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/77b18528c02e3d1f9c5588bbf3063877221c05b2))

## [0.39.3](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.39.2...v0.39.3) (2026-06-14)

### Поправљено

* **ucesnici:** add missing int_validator import crashing entity dialog ([ce2745a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/ce2745a39e5a5c3851a97ce99755dbe679b89721))

## [0.39.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.39.1...v0.39.2) (2026-06-13)

### Поправљено

* **about:** route manual update check through license server when LICENSED ([864e1d7](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/864e1d7923dc7a2918a0e99e71f5f32e71038974))
* **dialogs:** fix RowEditDialog crash + remove emoji from UI ([e18a054](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/e18a054e7d4d4b5b61bd4b68a341ab21fce67976))

## [0.39.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.39.0...v0.39.1) (2026-06-13)

### Поправљено

* **ucesnici:** surface silent failures in add/edit party dialogs ([8a50f22](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/8a50f229d4fa1b6b174073cf1b808b848c18cf58))

## [0.39.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.38.0...v0.39.0) (2026-06-13)

### Додато

* **ucesnici:** add Generate Template button in card 3 (Lists) ([73845d0](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/73845d08b8ce1fbfc810c8a3ee2e5bda153926b2))

## [0.38.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.37.0...v0.38.0) (2026-06-13)

### Додато

* **release:** upload OIK_Setup.exe to license server after GitHub Release ([da0e06b](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/da0e06b6642ac2db5f766aa02b33026157209174))

## [0.37.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.36.0...v0.37.0) (2026-06-13)

### Додато

* **izmene:** add amendment resolution generator (§7) ([0fd5d22](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/0fd5d229f16c765b5fa36933beb4d849e3b017bf))

## [0.36.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.35.0...v0.36.0) (2026-06-13)

### Додато

* **corrections:** add search bar to Places tab ([88346b0](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/88346b0b8b3b214258cc9953b2162be74d8daa05))
* **phase2:** enforce cutoff date in inbox picker ([a435b02](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/a435b0217585f5d2366771b33b83ba4d24dca6c8))
* **phase3:** add send-resenja-to-members button ([cddf77c](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/cddf77cbd06efdd949d5f170d17cd4950fe263f6))

## [0.35.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.34.0...v0.35.0) (2026-06-13)

### Додато

* **§7:** show cutoff date banners in Phase 2 and Phase 2.5 ([d235732](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/d2357323793cfd7850e14450b450b4449221648b))

## [0.34.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.33.0...v0.34.0) (2026-06-13)

### Додато

* cutoff dates, onboarding gate, daily auto-backup ([4c9a256](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/4c9a256f73b20e9660927f7f9296ccae8966bd8e))

## [0.33.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.32.0...v0.33.0) (2026-06-10)

### Додато

* **licensing:** bake server URL into installer at release build time ([b3f0f68](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/b3f0f6865dd5f42cb6c973439db18fa4b892fc61))

## [0.32.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.31.0...v0.32.0) (2026-06-09)

### Додато

* **installer:** rename app to OIK, add restore-from-backup page ([36b6099](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/36b60995ab5c66bd1bfba309704e6a2738bd3ed4))
* **restore:** §5 — restore from backup zip ([0760d8d](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/0760d8d84f5e8b7e4c6b7518ac70fbf9e06a8e41))
* **settings:** Excel import for electoral lists (Учесници card 3) ([5ba009d](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/5ba009db90610418897b11754aecffa69b77af8d))
* **settings:** merge Странке+Кандидати into cascading Учесници tab ([a9adeca](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/a9adeca0ec02ad719f601794aacbbf125dd200d3))

### Рефакторисање

* **settings:** rename Ентитет → Листа in Учесници tab UI ([532ad99](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/532ad99d4d4b671e7c8395053dbd1897164afaf0))

## [0.31.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.30.0...v0.31.0) (2026-06-07)

### Додато

* **prosireni:** Phase F — subject token rider, audit log differentiation, prosireni Outlook import ([38101bb](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/38101bba8296d39f343f22e1ec0eedc8613c7ed1))

## [0.30.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.29.0...v0.30.0) (2026-06-07)

### Додато

* **prosireni:** Phase E — Проширени sastав workflow goes live ([060690a](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/060690a612238f477be8aaecfeebbc70f45d9ffb))

## [0.29.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.28.0...v0.29.0) (2026-06-07)

### Додато

* **workflow:** Phase D — phase functions consume WorkflowSpec ([0a1b886](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/0a1b886bb2817c649560378a45e44330b9222ddb))

## [0.28.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.27.0...v0.28.0) (2026-06-07)

### Додато

* **gui:** Phase C — Кандидати 4th inner tab under Избори ([320d0a4](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/320d0a4d185f3e539f079ca2c8fe369ab7765b3a))

## [0.27.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.26.0...v0.27.0) (2026-06-06)

### Додато

* **validation:** Phase B — cross-check + 18+ + canonical-name resolution ([620bd5e](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/620bd5e401971a3be40cea2b7304f2ef211289d2))

## [0.26.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.25.0...v0.26.0) (2026-06-06)

### Додато

* **stalni:** A5 — empty-slot gate + načelnik appointment + audit-log section ([a6628c6](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/a6628c6dac3e40c9b1cb221548305a17fd9e3985))

## [0.25.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.24.0...v0.25.0) (2026-06-06)

### Додато

* **workflow:** A4 — WorkflowSpec skeleton + STALNI_SPEC + PROSIRENI_SPEC ([cbcd928](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/cbcd928051ef03a9ad52f3083713f26dec6bc558))

## [0.24.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.23.0...v0.24.0) (2026-06-06)

### Додато

* **candidacies:** A3 — candidates registry data model + Excel I/O ([299e5cf](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/299e5cf38c51c7ebf196407028e0c2c2ec005057))

## [0.23.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.22.0...v0.23.0) (2026-06-06)

### Додато

* **jmbg:** A2 — date_of_birth + at_least_18 helpers; validator delegates to core ([3597bb0](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/3597bb0c4245fc562552e1240f0da482e5d8d240))

## [0.22.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.21.2...v0.22.0) (2026-06-06)

### Додато

* **ui:** A1 — input sanitation pass; SingleLineEdit gains validator hook ([14d5bde](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/14d5bded24725a45fe2484d10f2cedcca44ff84b)), closes [#c0392](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/c0392)

## [0.21.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.21.1...v0.21.2) (2026-06-06)

### Изглед / UX

* **phase3:** banner moves into «Покретање и резултати» card; preview gets 70% width ([faa80b4](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/faa80b4c4dfc380cac76e3d24410a3e97a2af75a))

## [0.21.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.21.0...v0.21.1) (2026-06-05)

### Изглед / UX

* **phase3:** preview shows rendered text blocks; errors+buttons moved out of splitter ([15ab8e7](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/15ab8e716ac085e0c1d3181be11ac55b32f4a144))

## [0.21.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.20.0...v0.21.0) (2026-06-05)

### Додато

* **phase3:** sub-broj per BM + left/right layout with live preview; consolidate Document fields ([3081ee3](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/3081ee34339ace929cfca07c851f62655ff65d53))

## [0.20.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.19.0...v0.20.0) (2026-06-05)

### Додато

* **email:** Thunderbird inbox via MBox parsing; Phase 2 unblocked for Outlook-less clients ([6f3c9ae](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/6f3c9ae00a74d611f4153b68da1eb17718de5bec))

## [0.19.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.18.0...v0.19.0) (2026-06-05)

### Додато

* **corrections:** mark Phase 2 error rows in Сви чланови + add Е-пошта column ([3531ad1](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/3531ad15b96ddf23b098a35ceec46f6b1fce1c24))

## [0.18.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.17.0...v0.18.0) (2026-06-05)

### Додато

* **email:** subject-token rider for Phase 1 send + Phase 2 inbox filter ([dede673](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/dede6736412347d9e96a14e26c97f8a28e6feb33))

## [0.17.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.16.0...v0.17.0) (2026-06-05)

### Додато

* **email:** Thunderbird send via CLI + dispatcher abstraction over Outlook/Thunderbird ([f37cd05](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/f37cd054c41b2e8e47d331841486a99254634880))

## [0.16.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.15.2...v0.16.0) (2026-06-05)

### Додато

* **ui:** SingleLineEdit with visible horizontal scrollbar for overflowing fields ([7b94ffd](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/7b94ffd243faafafa8fea603efd6f96fade8e05d))

## [0.15.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.15.1...v0.15.2) (2026-06-04)

### Рефакторисање

* **ui:** extract SearchableTable + RowEditDialog; migrate Странке + Бирачка места ([3b8a3a8](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/3b8a3a86bbd6391135211c642e9e649f4d1282b0))

## [0.15.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.15.0...v0.15.1) (2026-06-04)

### Поправљено

* **ui:** legible table-cell editor + unified Save button text; queue Thunderbird+tables refactor ([0da5468](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/0da5468419a52f888cb017e0f1a2f4700a991464))

## [0.15.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.14.0...v0.15.0) (2026-06-03)

### Додато

* **backup:** move to sidebar, narrow scope to settings+database, rename to Резервна копија ([7fbdf6c](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/7fbdf6c035d793dda8c4b86ae06ad1b7c94c3ea4))

## [0.14.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.13.1...v0.14.0) (2026-06-02)

### Додато

* **installer:** bundle uninstaller exe + force-include pywin32 modules ([7515b34](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/7515b34bacc099f082c0beeb402aeff12081d81c))

## [0.13.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.13.0...v0.13.1) (2026-06-02)

### Поправљено

* **outlook:** inbox picker shows zero messages on pywin32 installs without win32timezone ([6bc2280](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/6bc2280c19818b85aa6490faa71ff5e0fb65d842))

## [0.13.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.12.0...v0.13.0) (2026-06-02)

### Додато

* license-server activation, HID-bound license file, demo mode ([deca1bf](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/deca1bf40205f844c67361f8399e5d7602dd9121))

## [0.12.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.11.0...v0.12.0) (2026-06-02)

### Додато

* backup to USB/cloud/email + autosave indicator (§4 + §6) ([2d64388](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/2d643884d115881bde8dc258e4edf3fb2a4d4973))

## [0.11.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.10.0...v0.11.0) (2026-06-02)

### Додато

* party contacts (§3) + Outlook draft per party from Phase 1 (§4) ([b89f310](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/b89f31025bbb7017cd6a576eab049e0fc3603d89))

## [0.10.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.9.2...v0.10.0) (2026-06-02)

### Додато

* Outlook-stamped submissions + per-party & combined audit log ([9c453bb](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/9c453bbe8b1ef07cca3a70d6e66d66530d8c8a65))

## [0.9.2](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.9.1...v0.9.2) (2026-05-29)

### Поправљено

* **ui:** FileDropZone.set_path stops emitting file_selected — kills startup loop ([74ded2e](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/74ded2e023770f2a5c2817da26601a5d552915e7))

## [0.9.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.9.0...v0.9.1) (2026-05-29)

### Поправљено

* **ui:** tab separator + menu font parity + card title clearance + dock height ([3c9ddcd](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/3c9ddcdf5171e93714eadf0d98de43e3b3db12ce)), closes [#A0](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/A0) [#C8CFE0](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/C8CFE0) [#A0](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/A0)

## [0.9.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.8.1...v0.9.0) (2026-05-29)

### Додато

* **ui:** V1 inner tabs, Шаблон as workflow tab 0, sidebar/dock alignment ([34fae00](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/34fae0048b77d132f839ad0e9b3118866da5716e))

## [0.8.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.8.0...v0.8.1) (2026-05-29)

### Поправљено

* **ui:** sidebar labels fit — Изборна конфигурација → Избори, drop (V2) inline hint ([76f53a0](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/76f53a0027576cd5b6d8c2b00e1dc5c865f14692))

## [0.8.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.7.0...v0.8.0) (2026-05-28)

### Додато

* **ui:** V1 sidebar — split Постaвке, V2 disabled, 220 px logo zone ([1b7f026](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/1b7f0260b94749134d1eb8a29c6a97db3421b4d2))

## [0.7.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.6.0...v0.7.0) (2026-05-28)

### Додато

* **ui:** V1 theming pass 1 — palette, scrollbar, tabs, cards, date picker ([d5f0973](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/d5f0973b00f9fbd0670678d120d25a8a7ec5e154)), closes [#1F2A44](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/1F2A44) [#8A92A6](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/8A92A6)

## [0.6.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.5.1...v0.6.0) (2026-05-27)

### Додато

* **banner:** auto-hide success messages after 5 s ([f655a98](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/f655a98373d6e6d4e44de0a7a63b5e97d48227e9))

## [0.5.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.5.0...v0.5.1) (2026-05-27)

### Поправљено

* visible A:D row tint + same-party conflict resolution + sticky save banner ([64fdaf2](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/64fdaf21c3cc545064ff5c112befd423040f794e)), closes [#D9E2F3](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/D9E2F3) [#2F5496](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/2F5496) [#C6](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/C6) [#006100](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/006100) [#FFC7](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/FFC7) [#9C0006](https://github.com/I-SOFT-Mionica/biracki-odbor/issues/9C0006)

## [0.5.0](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.4.1...v0.5.0) (2026-05-26)

### Додато

* top-of-sheet summary, sidebar restructure, per-row CF + 6 fixes ([dc14b90](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/dc14b90c1040a5cbe251ed655509ea1c1e9b50ff))

## [0.4.1](https://github.com/I-SOFT-Mionica/biracki-odbor/compare/v0.4.0...v0.4.1) (2026-05-26)

### Поправљено

* **gender:** expand male -а exception list from Wikipedia category ([d43d67c](https://github.com/I-SOFT-Mionica/biracki-odbor/commit/d43d67c26e574bd1f9ce41fd8227c328f03fe774))

# Changelog

Све значајне измене у овом пројекту се бележе у овом фајлу.

Формат: [Keep a Changelog](https://keepachangelog.com/sr/1.1.0/), верзионисање по [SemVer](https://semver.org/lang/sr/).

## [Unreleased]

## [0.4.0] — 2026-05-25

### Поправљено

- **Условно форматирање на колонама A:D у фајловима за странке** —
  v0.3.1 је користило `=$N4="✓"` и ослањало се на Excel-ову адаптацију
  релативних референци, али у пракси су сви редови читали N4. Сада
  `=INDIRECT("N"&ROW())="✓"` експлицитно рачуна N референцу по реду,
  без зависности од начина на који openpyxl серијализује CF правила.
- **Фаза 2 увоз: одбијени фајлови су били „тихи"**. Банер јесте писао
  „одбачено N", али је корисник пропуштао поруку при затварању file
  picker-а. Сада се после увоза јавља модални дијалог са списком
  одбачених фајлова и тачним разлогом за сваки.
- **Календари у Изборној конфигурацији и Фази 3** не остају више на
  старој/„nan" вредности кад је сачувани датум празан или непрепознат
  — увек се поставе на данас, тако да корисник не скролује уназад.

### Додато

- **Узајамни увоз свих Excel фајлова кроз безбедносни pipeline**.
  Шаблон, листа бирачких места и листа странака сада пролазе кроз исту
  проверу (величина / zip-валидност / макрои / OLE / спољне везе) као
  фајлови враћени од странака. Шаблон се **копира у канонску локацију**
  `<HOME>/sablon/Stalni_sastav.xlsx` — корисник више не може да упери
  програм на проиршан фајл, или да заборави где је оригинал.
- **„Образложење" се сада уређује у програму** — нови модални дијалог
  са картицама по параграфу, `**bold**` markdown синтаксом и видљивим
  placeholder-има. Раније је дугме отварало `obrazlozenje.json` у
  Notepad-у, што правницима није било интуитивно.
- **Дневник лог-фајлова са самоопис именом**. Сваки фајл се зове
  `YYYY-MM-DD.log` — активан фајл је данашњи, претходни дани остају
  поред њега. Не треба отварати фајл да би се видело који дан покрива.
- **Заштита од губитка измена у Поставкама**. Свака подешавачка
  страница сада прати свој „dirty" флег; при покушају преласка на
  другу страницу или изласку из програма са несачуваним изменама,
  програм пита: Сачувај / Одбаци / Откажи. Кориснике то спречава од
  тихог губитка података при tab-switch-у.

### Тестови

- Регресиони тест на CF формулу — траже се `ROW()` у формулама за A:D.
- Round-trip тест на `parse_markdown_paragraph` /
  `render_paragraph_markdown` (7 случајева).
- Логовање — име активног фајла мора почети данашњим ISO датумом;
  ротациони namer мора да преименује у `<date>.log` формат.
- 252 теста зелено.

## [0.3.1] — 2026-05-25

### Безбедност / отврдњавање

- **Sheet protection семантика поправљена**: бул-флегови у
  `phase1_generate.py` били су инвертовани у односу на OOXML норму
  (`True` значи „закључано"). Колоне у фајловима за странке могле су се
  „Унхиде"-овати, што је откривало скривену маркер ћелију `M1`.
  Сада су `formatCells`, `formatColumns`, `formatRows`, `insert*`,
  `delete*`, `pivotTables`, `objects`, `scenarios` сви постављени на
  `True` (блокирано). `sort` и `autoFilter` су допуштени за корисност.
- **Маркер ћелија M1 и колона N (Провера)**: добиле `hidden=True` уз
  `locked=True` — формула не може да се види у формула-траци чак ни кад
  је ћелија изабрана.

### Валидација уноса у фајловима за странке

- **Број телефона** строжи: бивша провера је гледала само дужину
  (`textLength >= 6`). Сада: custom формула
  `=AND(LEN(J4)>=6, ISNUMBER(VALUE(J4)), LEFT(J4,1)="0")` — мора
  садржати само цифре и почети нулом (нпр. „064..."). Ћелија има
  `number_format = "@"` тако да водећа нула остаје при ручном уносу.
- **Капитализација имена и презимена**: warning-стил DV на колонама E и F
  `=EXACT(E4, PROPER(E4))` — упозорава кад прво слово сваке речи није
  велико. Жута CF-ознака паралелно хвата paste-операције (DV не активира
  на paste). „Марко", „Ана Марија", „Поповић-Срећковић" пролазе.
- **Е-пошта**: DV на колони K
  `=AND(ISNUMBER(SEARCH("@",K4)), ISNUMBER(SEARCH(".",K4,SEARCH("@",K4))), LEN(K4)>=5)`
  — Excel нема regex, али SEARCH-композиција покрива основни облик
  (мора садржати @ и тачку после њега).
- **Условно форматирање на колонама A:D**: позадина реда се мења у
  зелено / црвено зависно од стања колоне N (провера ЈМБГ). Цели редови
  су сада на први поглед скенирабилни — паркетар не мора да тражи у
  колони N.

### Логовање

- **Дневна ротација уместо величинске**: `TimedRotatingFileHandler` са
  `when="midnight"` и `backupCount=30`. Активан дан се увек уписује у
  `app.log`; претходни дани добијају суфикс `.YYYY-MM-DD`. На Windows-у
  нема `logrotate` сервиса, тако да је временска ротација у процесу
  природнији избор — спречава да активна сесија изгуби рани контекст
  због величинске границе.

## [0.3.0] — 2026-05-24

### Додато

- **„Увези фајлове…" дугме у Фази 2** — мулти-селект picker за враћене .xlsx
  фајлове странака. Сваки фајл прође кроз безбедносни и идентитетски
  pipeline пре копирања у `popunjeni/`:
  - Безбедност: одбацује > 10 МБ, < 1 КБ, не-zip, фајлове са макроима
    (`xl/vbaProject.bin`), OLE угњеждене објекте (`xl/embeddings/`),
    спољне везе (`xl/externalLinks/`) и сумњиве zip-bomb компресије.
  - Идентитет: Phase 1 уграђује ознаку `BO/{election_uuid}/{party}` у
    скривену+закључану ћелију `M1`. Увоз одбија фајлове без ознаке,
    из других избора, или где је странка у ознаци ≠ странка у редовима.
  - Канонско име: усвојен фајл се преписује на `popunjeni/{party}.xlsx`,
    тако да парти-сајд итерација имена (`СНС_v2.xlsx`, `СНС_final.xlsx`)
    нестаје — наш фолдер увек има само најновију верзију.
- **Перзистентни кеш агрегације** (`<HOME>/cache/popunjeni.json`):
  - mtime+size кључ + election-UID scope; mismatch брише кеш при учитавању.
  - Атомично писање (`.tmp` + rename), сигурно на pad.
  - Фаза 2 поново-агрегација прескаче парсирање за непромењене фајлове.
- **Фаза 2.5 → нови таб „Падежи места"** — за свако јединствено место у
  master табели приказује аутоматски генитив (правило-базирано) и омогућава
  корисничку измену; узорак реченице се ажурира уживо. Корисничке измене
  се чувају у `places_genitive.json` (CMS-стил: seed при првом покретању,
  ажурирања никад не пишу преко).
- **Подељена колона имена** у фајловима за странке: уместо једне колоне
  „Име и презиме", сада су две одвојене (Е=Име, F=Презиме). Excel
  auto-suggest помаже при понављајућем уносу. Шема: 12 колона у фајловима
  за странке, 13 у master табели.
- **JMBG-name cross-check**: позиција 10 у ЈМБГ-у одређује пол; ако се
  не слаже са претпостављеним полом из имена (хеуристика на -а суфикс +
  exception листа за Никола, Лука, Илија, Андрија, Алекса, Матија, …),
  емитује се `JMBG_GENDER_MISMATCH` warning. Покрива замена имена↔презиме
  и грешке у куцању ЈМБГ-а.
- **Падеж места у Phase 3 решењима**: „из {место}" сада прелази кроз
  `place_to_genitive`. Аутоматска правила покривају -ац (Алексинац →
  Алексинца), компоновани придев+именица (Сремска Митровица → Сремске
  Митровице) и регуларне -а/-о/-е/-и завршетке. Изузеци (Шапца, Чачка)
  у user override фајлу.
- **„Посланичке групе" падежно усклађено** у proposal колони решења —
  нормализује било који унесен облик (Посланичка група X / Посланичке
  групе X) у генитивни „на предлог Посланичке групе Y".
- **Деинсталер** (`python -m biracki_odbor.installer.uninstaller_main`)
  — wizard у четири стране, три независне опције (пречица / програмски
  фајлови / кориснички подаци), брисање корисничких података захтева
  типовано „БРИШИ" за потврду.
- **Видљива paste-resistant ЈМБГ провера** у фајловима за странке —
  нова колона N („Провера") са закључаном формулом која враћа „✓" / „✗"
  и условним форматирањем (зелено/црвено). Excel paste брише data
  validation и conditional formatting на колони G (ЈМБГ), али не и на
  закључаној колони N — корисник види ваљаност на први поглед чак и
  после copy-paste из CRM-а. Резимни ред додаје бројач неисправних
  ЈМБГ-а преко `COUNTIF(N4:Nn,"✗")`.
- **Календарски picker за датум седнице ОИК** у Фази 3 — исти QDateEdit
  + popup календар као за датум избора; почетна вредност је данашњи
  датум, генитивни облик („6. децембра 2026. године") се рачуна и
  приказује у засебном лабелу пре чувања у `election_config.json`.
- **Изузеци у предлогу пред местом** („из" vs „са") као засебан CMS-стил
  фајл `<HOME>/places_prepositions.json`. Seed садржи планине и узвишења
  (Авала, Космај, Копаоник, Златибор, Тара, Цер, Букуља, Маљен, Рудник,
  Стара планина), висоравни (Цетиње, Умка) и регионалне случајеве (Уб).
  Фаза 3 чита предлог per-место и пише „са Уба", „са Цетиња", „из
  Београда". Падежи места таб добија нову колону „Предлог" са inline
  уређивањем („из"/„са"); унос који није ни „из" ни „са" се нормализује.
- **Уредив текст образложења** као засебан JSON шаблон
  (`<HOME>/obrazlozenje.json`, seed pattern). Seed садржи канонске
  параграфе са `{rik_decision}` и `{municipality}` placeholder-има и
  bold flag-овима за „Чланом N." сегменте. Settings → Изборна
  конфигурација → дугме „Уреди текст образложења…" отвара фајл у
  OS-default уређивачу. Фаза 3 чита из шаблона уместо хардкодираних
  параграфа — измене закона се сада решавају без поновног буилда.

### Измењено (Фаза 3 — финесе у складу са референцом, ил. бр. 2)

- **„РЕШЕЊЕ" наслов** користи Times New Roman 16pt, болд, са letter-spacing од 80 (= 4pt међу словима). Раније је покушавано ручним размацима („Р Е Ш Е Њ Е") — сада је то OOXML атрибут на самом тексту „РЕШЕЊЕ".
- **Линија префикса врсте избора** („ЗА КООРДИНИРАНО СПРОВОЂЕЊЕ ИЗБОРА ЗА", „И ИЗБОРА ЗА") је на 10pt и **није болд**, док је линија са називом врсте (нпр. „НАРОДНЕ ПОСЛАНИКЕ НАРОДНЕ СКУПШТИНЕ") болд на основном фонту од 11pt — два различита визуелна нивоа, како је у референци.
- **Табела са називом бирачког места** је сада 14 cm широка (7938 twips), центрирана, без обзиром на ширину текстуалне области.
- **Тачка 1** је селективно болдована: само део „бирачко место број N." је болд, остатак параграфа је обичан, у складу са референцом. Раније је цео параграф био болд.
- **Параграфи унутар табеле чланова** имају `space_after=0` тако да редови нису додатно растегнути. Уклоњено експлицитно постављање `borders=nil` (постиже исти визуелни ефекат и без тога).
- **Вертикално поравнање колоне „Број"** (прва колона) у табели чланова је сада центрирано на свим редовима, а не само на оним са лабелом групе.
- **Прелом секције са 3-колонском поставком** уведен после редова „ОПШТИНСКА ИЗБОРНА КОМИСИЈА / ОПШТИНЕ УБ" — потпис („ПРЕДСЕДНИК", линија за потпис, име председника) рендерује се у левој трећини стране, како је у референци.
- **Линија за потпис** (између „ПРЕДСЕДНИК" и имена председника) је сада 1×1 табела ширине 4.8 cm са **видљивом доњом ивицом** (танка црта), а не више невидљива (раније је била размакни placeholder без линије).

### Измењено (Фаза 3 — усклађивање са референтним документом)

- **„РЕШЕЊЕ" наслов без размака међу словима** (раније „Р Е Ш Е Њ Е"), на величини основног текста.
- **Врсте избора су подељене на две линије** — префикс („ЗА КООРДИНИРАНО СПРОВОЂЕЊЕ ИЗБОРА ЗА") стоји посебно, име врсте („НАРОДНЕ ПОСЛАНИКЕ НАРОДНЕ СКУПШТИНЕ") у следећем реду. Раније је целo стајало у једном реду на 9pt.
- **Тачка 1** ("У бирачки одбор у сталном саставу за…") је сада целом дужином подебљана, у складу са референцом.
- **Ширине колона у табели чланова** усклађене са референцом: 324 / 1736 / 2193 / 1417 / 3968 twips.
- **Вертикално поравнање** у табели чланова: ред са лабелом (1)/2)/3)) центрирано вертикално; ред са заменом подразумевано (горе).
- **Образложење**: параграфи закона („Чланом 35…", „Чланом 34…", „Чланом 36…", „Чланом 89…", „Чланом 91…") су болд; контекстни параграфи („У складу са Одлуком…", „(АКО НЕКА…)" и закључна реченица) нису.
- **„Број" и „У Убу" редови** су у подразумеваном поравнању (нема `<w:jc>`), не JUSTIFY.
- **„ПРЕДСЕДНИК" и име председника** су центрирани, не десно поравнати.
- **Празно поље за печат** — 1×1 табела без оквира (~4.8 cm) између „ПРЕДСЕДНИК" и имена председника, да резервише физички простор за печат.

### Измењено (Фаза 3 — изглед решења)

- **Образложење сада почиње на новој страници** (page_break_before на наслову), уместо да се одваја са шест празних редова који су често пуштали празну прву страницу.
- **Доња маргина повећана на ~3 cm** да остане места за печат/потпис на дну сваке стране. Циљ је да се свако решење одштампа на тачно две стране (диспозитив + образложење), уз простор за оверу.
- **Линија врста избора је сада увек на једном реду** (фонт смањен на 9pt само за те линије), уместо да се дугачке формулације (нпр. „ИЗБОРА ЗА НАРОДНЕ ПОСЛАНИКЕ НАРОДНЕ СКУПШТИНЕ") преламају на два реда.
- **Табела са називом бирачког места**: уместо квадрата са четири линије, сада се види само средња линија. Назив седи „на линији" (доње поравнање у горњем реду), а ознака „(назив и адреса бирачког места)" је испод ње.
- **Уклоњени празни редови** изнад тачке 1, између тачке 1 и табеле чланова, и испод табеле чланова — да назив бирачког места и листа чланова не „плутају" окружени великим белинама.
- **Табела чланова** сужена тако да тотал ширине колона буде једнак ширини текстуалне области (раније ~1 cm шира од остатка текста). Нова расподела: 360 / 1700 / 2700 / 1700 / 3178 twips.
- **Колона „на предлог" у табели чланова** сада има две линије: ознака „на предлог Посланичке групе" (мали фонт, 9pt) у првом реду, а назив посланичке групе (нпр. „Александар Вучић — Заједно можемо све") у другом реду, истом величином као и име члана (11pt).
- **Размак у образложењу** стегнут (`space_after_pt 6 → 3`) тако да цело образложење + потпис/печат места стане на другу страну.

### Перформансе

- **Паралелизам у Фазама 1/2/3**: користи се `concurrent.futures.ProcessPoolExecutor` (`max_workers = min(4, cpu_count)`) за независне фајл-операције. Прагови су подешени тако да за мале радне скупове остане секвенцијална путања (нема процеса).
  - Фаза 1: писање по-странка .xlsx — паралелно када има ≥ 6 странака.
  - Фаза 2: читање враћених фајлова — паралелно када има ≥ 6 фајлова. Писање master табеле остаје сериjално (једна ZIP датотека).
  - Фаза 3: писање .docx по бирачком месту — паралелно када има ≥ 8 БМ. Очекивано на 105 БМ: ~5 s → ~1.5 s.
- `multiprocessing.freeze_support()` се позива у `__main__.py` пре било ког Qt кода — обавезно за PyInstaller бундл.
- **Фаза 2 read_party_file** пребачено са `ws.cell()` на `ws.iter_rows(values_only=True)` (исто као master).
- **CorrectionsTab Сви чланови табела** пуни се у пакетном `setUpdatesEnabled(False) + blockSignals(True)` блоку — нема јанка при отварању 630-редног мастера.

### Поправљено

- `_resolve_desktop` обогаћен — препознаје и Work/School OneDrive фолдере (`OneDrive - Company\Desktop`); кроз glob претражује profile, не само хардкодоване путање.
- `create_desktop_shortcut` сада верификује да је .lnk заиста уписан пре него што врати успех — антивирус карантина или сличан силент-фејл се сада логује и враћа None.

## [0.2.0] — 2026-05-23

### Додато

- **Лева бочна трака** са секцијама Поставке / Радни ток / О апликацији; топ-табови се мењају зависно од изабране секције. Прозор се отвара максимизован.
- **О апликацији**: верзија, линк на GitHub репо, дугме „Провери ажурирање" (ручна провера) и угнежђено упутство.
- **Календар за датум избора**: QDateEdit са поп-ап календаром у Изборној конфигурацији; Цирилични „Пун облик" и „Генитив (израчунат)" се аутоматски рачунају (`config/declension.py`).
- **Логовање**: ротирајући `~/Biracki_Odbor/log/app.log` (1MB × 5). Прекидач „Опширно логовање" у Поставке ОИК → Систем; на сваком стартовању се чита из `app_settings.json`.
- **Excel увоз/извоз** за бирачка места и за пуне називе странака (по узору на постојеће дугме за шаблон).
- **Празан Stalni_sastav.xlsx** се аутоматски испушта у `sablon/` приликом инсталације (или ручно из Фазе 1 → „Креирај празан шаблон…").
- **OIK икона** за главну апликацију, инсталер и install фасциклу (Explorer прави desktop.ini уз `icon.ico`).

### Измењено

- **Поставке ОИК**: Општина (3 падежна облика) и Председник су бок-о-бок; „Пун назив комисије" је цела ширина; „Пун назив бирачког места" се аутоматски формира као „<Назив> — <Општина>" приликом чувања; колона „Број" у табели бирачких места не реагује на скрол точкићем и не сече цифре.
- **Изборна конфигурација**: ставке „date_genitive", „year" и „types_upper" се рачунају у програму (`declension.py`), не уносе се ручно. Врсте избора су чекбокс-листа (Председнички / Парламентарни / Покрајински / Локални) уместо слободног уноса.
- **Заштита фајлова за странке** (лозинка) је пресељена са Поставке ОИК на Изборну конфигурацију — мења се сваке године.
- **Фаза 3** има поља „Датум седнице" и „Број седнице"; раније су били у Поставкама, али се мењају при свакој седници, не по циклусу.
- **Р.бр.** је сада глобални UID слота: председник на БМ 2 је р.бр. 7 и у master табели и у сваком фајлу странке.
- **JMBG**: тврда контрола MOD 11 у Excel data validation-у фајлова за странке (раније само бојење); master.xlsx добија исти црвено/зелено визуелни сигнал.
- **Инсталер** сведен на 4 стране (Добродошли → Локација → Инсталирање → Завршено). Подразумевана локација је одмах прихваћена (раније је тражио „Преглед…"). Дугме за пречицу је пресељено са инсталера у Поставке ОИК → Систем, тако да корисници могу да направе пречицу било кад.
- **Шаблон Stalni_sastav.xlsx** има свог власника: Поставке ОИК → „Радни шаблон". Фазе 1 и 2 само приказују „Шаблон: <путања>" — нема више дуплираних drop zone-ова.

### Поправљено

- **Пречица на радној површини** више не пада на ћирилично име: дефолт је „OIK" (ASCII), а PowerShell позив користи `-EncodedCommand` (UTF-16 LE base64) као одбрана у дубину.
- **OneDrive-преусмерен Desktop** на Win 11 се правилно проналази преко `SHGetFolderPathW(CSIDL_DESKTOPDIRECTORY)`.
- **Лажна упозорења „Изборна конфигурација садржи примерне вредности"** — уклоњена; ватала су се на стварне вредности кад се корисников ОИК поклапа са узорним фајлом.
- **Excel увоз** одбија фајл који не одговара очекиваним заглављима (нпр. ако корисник изабере Stalni_sastav.xlsx за увоз странака), уместо да тихо учита смеће.
- **Smoke тест** више не покреће update checker и не оставља QThread за собом.

### Перформансе

- **`read_master`** (учитавање агрегиране табеле коју генерише Фаза 2) пребачено са `ws.cell()` на `ws.iter_rows(values_only=True)` (у read_only режиму је first био O(N²)) и добило mtime+size кеш. На корисниковој машини са 105 бирачких места:
  - прво учитавање: **27 s → 45 ms**;
  - поновно учитавање без промене фајла: **27 s → 1 ms**;
  - снимање Изборне конфигурације (које кроз `election_changed` сигнал поново тригерује Фаза 3 preflight): **27 s → 11 ms**.
- Сваки phase tab има `@log_timing` декоратор; следеће спорости се могу таргетирано пронаћи у `app.log`.

## [0.1.0] — 2026-05-21

### Додато

- Прво издање. PySide6 GUI са 6 табова (Поставке ОИК + Изборна конфигурација + Фазе 1/2/2.5/3).
- JMBG MOD 11 валидација; per-row провере (име, телефон, функција).
- Фаза 1: генерисање по-странка фајлова са локованим ћелијама.
- Фаза 2: агрегација враћених фајлова у `master/zbirana_tabela.xlsx`.
- Фаза 2.5: корекције (конфликти, замене, ручне измене) са JSONL аудит логом.
- Фаза 3: генерисање Word решења по бирачком месту (python-docx).
- PyInstaller инсталер са визардом за подешавање install фасцикле.
- GitHub Actions CI + release pipeline; in-app updater са opt-out.
