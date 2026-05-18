# Changelog

## Unreleased

### Important Upgrade Note

- Existing users must re-run `onboard_user` after upgrading to the HTML renderer + extractor fixes. Older `sections.json` files may contain corrupted contact fields (for example duplicated email or incorrect location).

## [0.2.0](https://github.com/thedandano/pi-apply/compare/v0.1.0...v0.2.0) (2026-05-06)


### Features

* add before/after scores to report, surface finalized_at in state ([1a67776](https://github.com/thedandano/pi-apply/commit/1a6777643d739aaa4a8e014e854cc2ad08cb0a83))
* **epic3-m1:** deps + models (CreatedStory, CompiledProfile, OrphanedSkill) ([75c7f9e](https://github.com/thedandano/pi-apply/commit/75c7f9e5feae6583f003fa473d1fa1724d47ddd1))
* **epic3-m2:** resume repository (save, get, list — XDG-aware) ([ad3d81e](https://github.com/thedandano/pi-apply/commit/ad3d81eb4821890028acda8531506e5193a09095))
* **epic3-m3:** accomplishments repository (AccomplishmentsStore, atomic JSON) ([f0f989d](https://github.com/thedandano/pi-apply/commit/f0f989d461148052e5876516dac50ffd81852b47))
* extract_sections — SectionMap output from resume text (M3) ([40b5e32](https://github.com/thedandano/pi-apply/commit/40b5e32ac44dd3b4a75f9e2ed2f8e3aed622aae7))
* implement epic 1 packaging and ci ([18b7c22](https://github.com/thedandano/pi-apply/commit/18b7c22296336d730d8c0cb4cd4f34ebaba06c0f))
* **profile:** add ProfileCompiler with three-tier skill union and coverage lint ([fab873c](https://github.com/thedandano/pi-apply/commit/fab873c712b86c07ac59d7726b6dcfce3c530150))
* **profile:** M5 WikiRenderer — experience pages and index ([8005547](https://github.com/thedandano/pi-apply/commit/8005547a9d9a2b34a37c8b8ee73e63df3908be99))
* **profile:** M6 wire profile nodes to real stores ([05b015d](https://github.com/thedandano/pi-apply/commit/05b015de2191f4767d90d27ead0469ec8430d868))
* **profile:** M6 wire profile nodes to real stores + update graph tests ([045c680](https://github.com/thedandano/pi-apply/commit/045c6805739e6f11d65a639992d59fb5369593e5))
* **profile:** M7 rewrite profile MCP tools to use real graph + nodes ([d255bf0](https://github.com/thedandano/pi-apply/commit/d255bf0078a1417d55e73de182b554e0566faa53))
* **profile:** M8 add compile_profile to graph interrupt_after ([ef8c414](https://github.com/thedandano/pi-apply/commit/ef8c4144b37117258217f99c7715a0b5333ff6a8))
* **profile:** M9 integration tests + smoke script update ([99a8c29](https://github.com/thedandano/pi-apply/commit/99a8c29e5f1f4035cec82f5b393e87869825f7ac))
* SectionMap data model + WikiStore + get_wiki_pages tool (M1+M2) ([2cf739c](https://github.com/thedandano/pi-apply/commit/2cf739c4b3e9adbc5ebfdfc181f57e00acd604aa))
* wire holistic tailor end-to-end ([303f464](https://github.com/thedandano/pi-apply/commit/303f464a16e80b7488a4654ee7aeaf92fe21aaf8))


### Bug Fixes

* move inline imports to module-level; guard empty primary_skill ([95761b5](https://github.com/thedandano/pi-apply/commit/95761b5d2cc42d78788545912e0f8022be314477))
* **type:** fix Pyright errors in test_server_profile.py ([be4b53a](https://github.com/thedandano/pi-apply/commit/be4b53a7f016e57e3dd41f94049fa20ea09b67fb))


### Documentation

* mark Epic 2 complete, update dependency graph and next action ([1bf5832](https://github.com/thedandano/pi-apply/commit/1bf5832cbfc6591e604bc2f9c551b286936d9994))
