# Sources and notices / 出典と通知

## English

IZCIVSwitch integrates the [civswitch-kit](https://gitee.com/mza1010/civswitch-kit); it does not
claim authorship of the Civ7 XSS, ns2jb Stage 2 engine or CivSwitch loader. This repository's
integration code is [GPL-2.0](LICENSE). Bundled projects retain their own terms; this short list
does not replace their licenses.

- **civswitch-kit** by mza1010: [GPL-2.0](kit/LICENSE) and [upstream notice](kit/NOTICE.md),
  crediting slapah's CivSwitch port and [kurumuz/ns2jb](https://gitlab.com/kurumuz/ns2jb).
- **CivSwitchLDN** by ItsNerisma: the included PC Lobby component derives from
  `iz2s-panel/iz2s-platform-run22`; its [GPL-3.0-only license](panel/engines/CivSwitchLDN/LICENSE)
  and [third-party notices](panel/engines/CivSwitchLDN/THIRD_PARTY_NOTICES.md) are retained under
  `panel/`.
- **Gezine/CivSwitch:** the Civ7 XSS and loader portions carry the [MIT notice](LICENSE-MIT-Gezine.txt).
- **IZlauncher 0.27** from [IZ2S Platform](https://github.com/byizmysh/IZ2S-Platform):
  `izlauncher/package/` includes the embedded loader and
  [IZ2S GPL-2.0 license](izlauncher/package/LICENSE-IZ2S.txt) and
  [Gezine MIT license](izlauncher/package/LICENSE-CivSwitch.txt). Its `boot.js`,
  `capsule-source.js`, `menu-capsule.bin`, `IZlauncher-027-FS.Civ7Save` and `pad-normalize.comp.spv`
  remain in the package.

The archives **exclude** console keys (`prod.keys`, `title.keys`), the third-party Switch 1
installer `civswitch-ldn-nx.nro`, firmware dumps, **personal** save backups and private runs.
They include the distribution templates `kit/save-tools/trigger-recreate/XSTRIG.Civ7Save` and
`izlauncher/package/IZlauncher-027-FS.Civ7Save`. The full Linux
archive includes the CivSwitchLDN component, its Linux x86_64 runtime and the required panel
structure, **not** the full `iz2s-panel` platform. The upstream kit's NOTICE describes *its own
complete package*, including an NRO omitted here; it does not mean this candidate contains that NRO.

---

## 日本語

IZCIVSwitchは[civswitch-kit](https://gitee.com/mza1010/civswitch-kit)を統合するもので、Civ7 XSS、ns2jb Stage 2エンジン、CivSwitchローダーの作者を名乗るものではない。
このリポジトリの統合コードは[GPL-2.0](LICENSE)。
同梱物はそれぞれ元の条件に従い、この一覧は原文のライセンスに代わらない。

- **mza1010のcivswitch-kit:** [GPL-2.0](kit/LICENSE)と[元のNOTICE](kit/NOTICE.md)を保持。
slapahのCivSwitch移植と[kurumuz/ns2jb](https://gitlab.com/kurumuz/ns2jb)に言及する。
- **ItsNerismaのCivSwitchLDN:** 同梱のPC Lobby部分は `iz2s-panel/iz2s-platform-run22` 由来。
`panel/` に[GPL-3.0-only](panel/engines/CivSwitchLDN/LICENSE)と[第三者通知](panel/engines/CivSwitchLDN/THIRD_PARTY_NOTICES.md)を残している。
- **Gezine/CivSwitch:** Civ7 XSSとローダー部分には[MIT通知](LICENSE-MIT-Gezine.txt)を維持。
- **[IZ2S Platform](https://github.com/byizmysh/IZ2S-Platform)のIZlauncher 0.27:** `izlauncher/package/` は内蔵ローダーと[IZ2SのGPL-2.0](izlauncher/package/LICENSE-IZ2S.txt)、[GezineのMIT](izlauncher/package/LICENSE-CivSwitch.txt)を含む。
`boot.js`、`capsule-source.js`、`menu-capsule.bin`、`IZlauncher-027-FS.Civ7Save`、`pad-normalize.comp.spv` も同梱する。

配布アーカイブには本体の鍵（`prod.keys`、`title.keys`）、第三者製Switch 1用インストーラー `civswitch-ldn-nx.nro`、FWダンプ、**個人の**セーブバックアップ、個人用runを**含めない**。
配布用テンプレート `kit/save-tools/trigger-recreate/XSTRIG.Civ7Save` と
`izlauncher/package/IZlauncher-027-FS.Civ7Save` は同梱する。
Linuxフル版に含むのはCivSwitchLDN部分・Linux x86_64ランタイム・必要なパネル構造であり、`iz2s-panel` 全体ではない。
元キットのNOTICEがNROに言及するのは**元キット全体**の内容で、この候補にNROが入っている意味ではない。
