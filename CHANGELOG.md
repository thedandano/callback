# Changelog

## Unreleased

### Important Upgrade Note

- Existing users must re-run `onboard_user` after upgrading to the HTML renderer + extractor fixes. Older `sections.json` files may contain corrupted contact fields (for example duplicated email or incorrect location).

## [2.0.0](https://github.com/thedandano/callback/compare/v1.0.1...v2.0.0) (2026-06-25)


### ⚠ BREAKING CHANGES

* composite weights and ExperienceFit semantics changed.

### Features

* cross-harness plugin (manifests, setup-plugin, uvx self-bootstrap) ([530e44a](https://github.com/thedandano/callback/commit/530e44aab9fc0e005907944ba8e9048471ecb410))
* keyword-match refinements, report decomposition, golden determinism test ([a01d5b3](https://github.com/thedandano/callback/commit/a01d5b385a9af83a83da138e93570a2472436dcb))
* PreferencesStore persistence for search preferences ([8a26f66](https://github.com/thedandano/callback/commit/8a26f66b76680f6f5e81f88a75620a5e6e1bd3c0))
* profile preferences wiring + init skill; de-PII job-search skills ([2f303f7](https://github.com/thedandano/callback/commit/2f303f7ba12ef5c6f61934de2e6898c75ddd4a96))
* scoring redesign v2 — reweight to 55/15/10/10/10, years-only ExperienceFit ([01f9cab](https://github.com/thedandano/callback/commit/01f9cabb83d663a0422d2d5fa837a9bb54f8a622))
* SearchPreferences domain model ([a3ada15](https://github.com/thedandano/callback/commit/a3ada15859e13903d23c246b1a7cc89f36a1d423))
* set/get_search_preferences MCP tools ([5a5bdd8](https://github.com/thedandano/callback/commit/5a5bdd804c4a640127ff8ba81b25f6d8a9cdbd8d))


### Documentation

* cross-harness plugin packaging design + plan ([f5d4fe9](https://github.com/thedandano/callback/commit/f5d4fe9a9ae4850858a260b13b0232c52c1d4c2f))
* **onboard-profile:** clarify section grouping is job_title-driven ([18712a2](https://github.com/thedandano/callback/commit/18712a2d5f7df0c28424fd2a3e83adfdd8834ad7))
* reframe callback as standalone post go-apply deprecation ([4461a2d](https://github.com/thedandano/callback/commit/4461a2dfbb479f4f15bd8010188d55ea1a3c77c3))
* search-preferences implementation plan ([cf3d5f0](https://github.com/thedandano/callback/commit/cf3d5f0ac7c29e136ea6196cce35a49a8aede0e4))
* search-preferences subsystem design spec ([8f6087e](https://github.com/thedandano/callback/commit/8f6087e0b97d69ef464ad55ebaa9e26abb8e5dbe))

## [1.0.1](https://github.com/thedandano/callback/compare/v1.0.0...v1.0.1) (2026-06-11)


### Documentation

* post-rename coherence sweep ([430424f](https://github.com/thedandano/callback/commit/430424f6d616eb82274e21876e998e69c45428b6))
* retro for v1.0.0 rename and migration ([fa7b1a3](https://github.com/thedandano/callback/commit/fa7b1a38b1d1be7d6e435d38aa74a0342351e51d))

## [1.0.0](https://github.com/thedandano/callback/compare/v0.5.0...v1.0.0) (2026-06-11)


### ⚠ BREAKING CHANGES

* CLI is now `callback`, env vars use the CALLBACK_ prefix, the import package is `callback`, and state lives under ~/.local/share/callback/.

### Features

* rename pi-apply to callback for v1.0.0 ([5807c84](https://github.com/thedandano/callback/commit/5807c840063fb6bbb88d99487996333cf634a56b))

## [0.5.0](https://github.com/thedandano/callback/compare/v0.4.1...v0.5.0) (2026-06-11)


### Features

* add LangSmith observability with thread grouping and redacted I/O ([21e90b4](https://github.com/thedandano/callback/commit/21e90b4f5474228b22428ef48d438c0e755c91cb))

## [0.4.1](https://github.com/thedandano/callback/compare/v0.4.0...v0.4.1) (2026-05-21)


### Bug Fixes

* stop codex project log registration ([55f31d2](https://github.com/thedandano/callback/commit/55f31d2bb964f64fd0edf2bcf3d8e391379dc560))

## [0.4.0](https://github.com/thedandano/callback/compare/v0.3.1...v0.4.0) (2026-05-21)


### Features

* add project-local callback logs ([1870e0d](https://github.com/thedandano/callback/commit/1870e0dbee5e86a4f029039b8babb3c8b67350e1))
* rank project candidates for tailoring ([a1d1985](https://github.com/thedandano/callback/commit/a1d19853e50a02bffaacbd633fb8bb2489833209))

## [0.3.1](https://github.com/thedandano/callback/compare/v0.3.0...v0.3.1) (2026-05-21)


### Documentation

* clarify callback architecture guidance ([d4c0af7](https://github.com/thedandano/callback/commit/d4c0af747cac81b5909b920a606ba80bd7f7743f))

## [0.3.0](https://github.com/thedandano/callback/compare/v0.2.0...v0.3.0) (2026-05-18)


### Features

* **cli:** add install-browsers, uninstall (--purge), and update commands ([881a45e](https://github.com/thedandano/callback/commit/881a45e4095818ecd7b28a333838048a9ec2b5e7))
* **extractor,profile:** improve PDF extraction and feed resume skills into compiler ([88f7712](https://github.com/thedandano/callback/commit/88f771250cdd736dc66b651dcb0329855b8eb307))
* **render:** switch resume PDFs to HTML ([326b714](https://github.com/thedandano/callback/commit/326b714d6a56e2fe68ff7a920fdffbc4afe2c474))
* **server:** browser check at startup + check_update MCP tool + update notification ([fb4e3cf](https://github.com/thedandano/callback/commit/fb4e3cf0a254b5db677f7626fb25b6e455028372))
* **server:** expose workflow diagnostics ([1e30785](https://github.com/thedandano/callback/commit/1e3078580ab7e9021c21a9b997de7ebbb9e02d32))
* **server:** remove resume_path from load_jd; add auto-discovery via registry ([34e1698](https://github.com/thedandano/callback/commit/34e16984db09f737bccadc6d1fa8a83b570ea306))
* use candidate-company naming for rendered resumes ([b1cf280](https://github.com/thedandano/callback/commit/b1cf2809b624bffd680112616715ba0d752bf91f))


### Bug Fixes

* **cli:** setup-mcp writes absolute binary path so Claude can find the server ([bfa0f76](https://github.com/thedandano/callback/commit/bfa0f765a84599a84e7390692dc84eb5b037e0bf))
* **profile:** stabilize resume parsing and onboarding ([d6895da](https://github.com/thedandano/callback/commit/d6895da2f37146ded74a90c80a7430d749b8758c))
* **render:** bundle Inter font; eliminate system font scan on first call ([a8a8ff9](https://github.com/thedandano/callback/commit/a8a8ff99916a1b0c426e7a94d5177fde1b371a44))
* **render:** tolerate browser test doubles ([70f2d3c](https://github.com/thedandano/callback/commit/70f2d3ca4b1a8c386ed52e5db8915715d523768a))


### Documentation

* add README with install, update, uninstall, and how-to-use ([db1f8a2](https://github.com/thedandano/callback/commit/db1f8a218168586c6a92f62ee1a630795ccf6d4d))

## [0.2.0](https://github.com/thedandano/callback/compare/v0.1.0...v0.2.0) (2026-05-06)


### Features

* add before/after scores to report, surface finalized_at in state ([1a67776](https://github.com/thedandano/callback/commit/1a6777643d739aaa4a8e014e854cc2ad08cb0a83))
* **epic3-m1:** deps + models (CreatedStory, CompiledProfile, OrphanedSkill) ([75c7f9e](https://github.com/thedandano/callback/commit/75c7f9e5feae6583f003fa473d1fa1724d47ddd1))
* **epic3-m2:** resume repository (save, get, list — XDG-aware) ([ad3d81e](https://github.com/thedandano/callback/commit/ad3d81eb4821890028acda8531506e5193a09095))
* **epic3-m3:** accomplishments repository (AccomplishmentsStore, atomic JSON) ([f0f989d](https://github.com/thedandano/callback/commit/f0f989d461148052e5876516dac50ffd81852b47))
* extract_sections — SectionMap output from resume text (M3) ([40b5e32](https://github.com/thedandano/callback/commit/40b5e32ac44dd3b4a75f9e2ed2f8e3aed622aae7))
* implement epic 1 packaging and ci ([18b7c22](https://github.com/thedandano/callback/commit/18b7c22296336d730d8c0cb4cd4f34ebaba06c0f))
* **profile:** add ProfileCompiler with three-tier skill union and coverage lint ([fab873c](https://github.com/thedandano/callback/commit/fab873c712b86c07ac59d7726b6dcfce3c530150))
* **profile:** M5 WikiRenderer — experience pages and index ([8005547](https://github.com/thedandano/callback/commit/8005547a9d9a2b34a37c8b8ee73e63df3908be99))
* **profile:** M6 wire profile nodes to real stores ([05b015d](https://github.com/thedandano/callback/commit/05b015de2191f4767d90d27ead0469ec8430d868))
* **profile:** M6 wire profile nodes to real stores + update graph tests ([045c680](https://github.com/thedandano/callback/commit/045c6805739e6f11d65a639992d59fb5369593e5))
* **profile:** M7 rewrite profile MCP tools to use real graph + nodes ([d255bf0](https://github.com/thedandano/callback/commit/d255bf0078a1417d55e73de182b554e0566faa53))
* **profile:** M8 add compile_profile to graph interrupt_after ([ef8c414](https://github.com/thedandano/callback/commit/ef8c4144b37117258217f99c7715a0b5333ff6a8))
* **profile:** M9 integration tests + smoke script update ([99a8c29](https://github.com/thedandano/callback/commit/99a8c29e5f1f4035cec82f5b393e87869825f7ac))
* SectionMap data model + WikiStore + get_wiki_pages tool (M1+M2) ([2cf739c](https://github.com/thedandano/callback/commit/2cf739c4b3e9adbc5ebfdfc181f57e00acd604aa))
* wire holistic tailor end-to-end ([303f464](https://github.com/thedandano/callback/commit/303f464a16e80b7488a4654ee7aeaf92fe21aaf8))


### Bug Fixes

* move inline imports to module-level; guard empty primary_skill ([95761b5](https://github.com/thedandano/callback/commit/95761b5d2cc42d78788545912e0f8022be314477))
* **type:** fix Pyright errors in test_server_profile.py ([be4b53a](https://github.com/thedandano/callback/commit/be4b53a7f016e57e3dd41f94049fa20ea09b67fb))


### Documentation

* mark Epic 2 complete, update dependency graph and next action ([1bf5832](https://github.com/thedandano/callback/commit/1bf5832cbfc6591e604bc2f9c551b286936d9994))
