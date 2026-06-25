# Changelog

## Unreleased

### Important Upgrade Note

- Existing users must re-run `onboard_user` after upgrading to the HTML renderer + extractor fixes. Older `sections.json` files may contain corrupted contact fields (for example duplicated email or incorrect location).

## [1.0.1](https://github.com/thedandano/callback/compare/v1.0.0...v1.0.1) (2026-06-11)


### Documentation

* post-rename coherence sweep ([430424f](https://github.com/thedandano/callback/commit/365728d1a03ea50bec94cce93a894a46c779c01f))
* retro for v1.0.0 rename and migration ([fa7b1a3](https://github.com/thedandano/callback/commit/31e41fad786dac72a8799e8e006860f36bf96cd9))

## [1.0.0](https://github.com/thedandano/callback/compare/v0.5.0...v1.0.0) (2026-06-11)


### ⚠ BREAKING CHANGES

* CLI is now `callback`, env vars use the CALLBACK_ prefix, the import package is `callback`, and state lives under ~/.local/share/callback/.

### Features

* rename pi-apply to callback for v1.0.0 ([5807c84](https://github.com/thedandano/callback/commit/db850ea9e8bfb9fa7eefbbb7766a43087ec2b67f))

## [0.5.0](https://github.com/thedandano/callback/compare/v0.4.1...v0.5.0) (2026-06-11)


### Features

* add LangSmith observability with thread grouping and redacted I/O ([21e90b4](https://github.com/thedandano/callback/commit/297588d486eb16c709572ef5057f511e486eb6f3))

## [0.4.1](https://github.com/thedandano/callback/compare/v0.4.0...v0.4.1) (2026-05-21)


### Bug Fixes

* stop codex project log registration ([55f31d2](https://github.com/thedandano/callback/commit/763d9cafb50d6bf3bcc23d1550c0688c686f1c2b))

## [0.4.0](https://github.com/thedandano/callback/compare/v0.3.1...v0.4.0) (2026-05-21)


### Features

* add project-local callback logs ([1870e0d](https://github.com/thedandano/callback/commit/5ca23011451256dc95ed0dd30a9553d3bfe72704))
* rank project candidates for tailoring ([a1d1985](https://github.com/thedandano/callback/commit/da74ecbb34671abd6e5e086a802c66f399901f9b))

## [0.3.1](https://github.com/thedandano/callback/compare/v0.3.0...v0.3.1) (2026-05-21)


### Documentation

* clarify callback architecture guidance ([d4c0af7](https://github.com/thedandano/callback/commit/7d6c6982be7724db59d60062bc7c6650065ab786))

## [0.3.0](https://github.com/thedandano/callback/compare/v0.2.0...v0.3.0) (2026-05-18)


### Features

* **cli:** add install-browsers, uninstall (--purge), and update commands ([881a45e](https://github.com/thedandano/callback/commit/ceccae0473282dbcb918a46514d98936743ae400))
* **extractor,profile:** improve PDF extraction and feed resume skills into compiler ([88f7712](https://github.com/thedandano/callback/commit/56b1151defd376dd31f6d7cc3f8be44000976c22))
* **render:** switch resume PDFs to HTML ([326b714](https://github.com/thedandano/callback/commit/19526702489ecb9690bdf0331c983c0f5b04f152))
* **server:** browser check at startup + check_update MCP tool + update notification ([fb4e3cf](https://github.com/thedandano/callback/commit/f7ad5acbea92cc0790d0bb5943f2baffc69230ee))
* **server:** expose workflow diagnostics ([1e30785](https://github.com/thedandano/callback/commit/e55d61bfb0123a729dd1f0505a2d2d186a9f5c78))
* **server:** remove resume_path from load_jd; add auto-discovery via registry ([34e1698](https://github.com/thedandano/callback/commit/89510d301b3ea4d62a26205922212c6b321b5afb))
* use candidate-company naming for rendered resumes ([b1cf280](https://github.com/thedandano/callback/commit/6256d406e7756e53cb949dd5f334d5d51e218ac7))


### Bug Fixes

* **cli:** setup-mcp writes absolute binary path so Claude can find the server ([bfa0f76](https://github.com/thedandano/callback/commit/1e77129f8e85f16f6bfc23356b51d7cfbcca7566))
* **profile:** stabilize resume parsing and onboarding ([d6895da](https://github.com/thedandano/callback/commit/bcfefcf5a00b03de4c42c4e87558c8f6cbcd5c05))
* **render:** bundle Inter font; eliminate system font scan on first call ([a8a8ff9](https://github.com/thedandano/callback/commit/d71752683f31c8da98bbfbc4e6b7375322c9fa71))
* **render:** tolerate browser test doubles ([70f2d3c](https://github.com/thedandano/callback/commit/0976633eda32c0a997096d4057bde7f6ce7668b1))


### Documentation

* add README with install, update, uninstall, and how-to-use ([db1f8a2](https://github.com/thedandano/callback/commit/22eafed30e106a59e13b687e77252f9c7576d696))

## [0.2.0](https://github.com/thedandano/callback/compare/v0.1.0...v0.2.0) (2026-05-06)


### Features

* add before/after scores to report, surface finalized_at in state ([1a67776](https://github.com/thedandano/callback/commit/150dd28ee2cdb0ead1a7039f4c11e7b8182a7296))
* **epic3-m1:** deps + models (CreatedStory, CompiledProfile, OrphanedSkill) ([75c7f9e](https://github.com/thedandano/callback/commit/f4eb5d834f4d56021376a9fb57ea3eae00628bdf))
* **epic3-m2:** resume repository (save, get, list — XDG-aware) ([ad3d81e](https://github.com/thedandano/callback/commit/622898f428353a7deef003d15644bdd08b85082c))
* **epic3-m3:** accomplishments repository (AccomplishmentsStore, atomic JSON) ([f0f989d](https://github.com/thedandano/callback/commit/0477e75529a9e81dd4b89b26efac972d61a5b00a))
* extract_sections — SectionMap output from resume text (M3) ([40b5e32](https://github.com/thedandano/callback/commit/2a72bcb47522f3f64078deefcd16242740da1872))
* implement epic 1 packaging and ci ([18b7c22](https://github.com/thedandano/callback/commit/1e389d17de4e4f0bbbfcb048c8a85b0b749a4b53))
* **profile:** add ProfileCompiler with three-tier skill union and coverage lint ([fab873c](https://github.com/thedandano/callback/commit/42b830ca9ee3f1c1c1cee86af7d526247e46cbe0))
* **profile:** M5 WikiRenderer — experience pages and index ([8005547](https://github.com/thedandano/callback/commit/9644480d25ab4622d76a2a7edb90a32d59f07696))
* **profile:** M6 wire profile nodes to real stores ([05b015d](https://github.com/thedandano/callback/commit/0c956d1141f4e34a59ed1b07e91e906d61bf65b3))
* **profile:** M6 wire profile nodes to real stores + update graph tests ([045c680](https://github.com/thedandano/callback/commit/7162b7e00424c5048a4bd5a382502669a78de8ab))
* **profile:** M7 rewrite profile MCP tools to use real graph + nodes ([d255bf0](https://github.com/thedandano/callback/commit/93b3a941db3fa4b403e0259e4396fb6bad61ed40))
* **profile:** M8 add compile_profile to graph interrupt_after ([ef8c414](https://github.com/thedandano/callback/commit/642104b511b49050723efc498b1391f368eb52d6))
* **profile:** M9 integration tests + smoke script update ([99a8c29](https://github.com/thedandano/callback/commit/752598cc3675fca9d8f400baea7dfbee8c4e00cd))
* SectionMap data model + WikiStore + get_wiki_pages tool (M1+M2) ([2cf739c](https://github.com/thedandano/callback/commit/4b736637ed16ee8c5c272f1acf92e0e302af1032))
* wire holistic tailor end-to-end ([303f464](https://github.com/thedandano/callback/commit/e8c7ac4921a0670b4fdf4a99faf02918cbda8f09))


### Bug Fixes

* move inline imports to module-level; guard empty primary_skill ([95761b5](https://github.com/thedandano/callback/commit/2f0cc91134df1e3cd066adccf9775564bb8bb2c5))
* **type:** fix Pyright errors in test_server_profile.py ([be4b53a](https://github.com/thedandano/callback/commit/b1279cdba6a6ff387f0217e5baf8965c0fce4867))


### Documentation

* mark Epic 2 complete, update dependency graph and next action ([1bf5832](https://github.com/thedandano/callback/commit/129e569bb16dfde124bcf23222b1bb7f3df2bb92))
