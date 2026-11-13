# IZCIVSwitch v0.2.0-rc.19

[English](#english) · [日本語](#日本語) · [README](README.md)

## English

This update adds language settings for a live Civ7 FS session and bundles
[civswitch-kit v1.0.3](https://gitee.com/mza1010/civswitch-kit).

- `civ-locale.cjs` inspects the current setting and can switch to 17 languages. It checks this boot's language mappings and saves a receipt for same-session restoration.
- The PC launcher stays open after `4/4 verified` and `FS ENDPOINT IS LIVE`. The 12-minute deadline applies to acquisition, not the held session.
- The updated kit adds SD album and FTP tools. FTP starts read-only; write access requires both engine and bridge opt-in.
- XSTRIG provides a loader entry for later boots; each boot needs its own FS connection.

In a Civ7 session using the earlier kit, `ja`→`ko` was acknowledged, two readbacks returned `ko`, and System Settings appeared in Korean. After a full reboot, Settings and two read-only checks showed `ja` again. The post-FS language path is unchanged in kit v1.0.3.

**Downloads:** `IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz` includes the PC Lobby runtime; `IZCIVSwitch-0.2.0-rc.19-source.zip` requires a separate compatible panel for Lobby mode. Check the archives with `IZCIVSwitch-0.2.0-rc.19-assets.sha256`. Setup, commands and the complete file list are in the [README](README.md).

---

## 日本語

Civ7のFS接続中に使える言語設定を追加し、[civswitch-kit v1.0.3](https://gitee.com/mza1010/civswitch-kit)を取り込んだ。

- `civ-locale.cjs` で現在の設定を確認し、17言語に変更できる。今回の起動の言語対応を確認し、同じ接続中の復元に使う記録を残す。
- PCランチャーは `4/4 verified` と `FS ENDPOINT IS LIVE` の後も接続を保持する。12分の制限はFS取得中に適用される。
- 更新したキットにSDアルバムとFTPツールを収録。FTPの初期状態は読取り専用で、書込みにはエンジンとブリッジ双方の許可が必要。
- XSTRIGは次回以降のローダー入口を残す。FS接続は起動ごとに取り直す。

以前のキットを使ったCiv7の接続では、`ja`→`ko` の書込みにACKが返り、2回の読戻しで `ko`、本体設定画面で韓国語を確認した。フル再起動後は設定画面と2回の読取りで `ja` に戻った。キットv1.0.3でもFS取得後の言語処理経路は同じ。

**配布ファイル:** `IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz` にはPC Lobbyランタイムを同梱。`IZCIVSwitch-0.2.0-rc.19-source.zip` でLobbyを使う場合は互換パネルを別途用意する。`IZCIVSwitch-0.2.0-rc.19-assets.sha256` で照合できる。準備、コマンド、収録内容は[README](README.md)へ。

---

# Release notes — 0.1.0

Released: 2026-11-11

## Verified

Full hardware run through the Lobby path:

```
run: switch2-nTDhp6
verified: True
26/26 pipeline stages complete
retainedEndpoint.ready: True
319 496 RPC exchanges
FS execution verified. Original instructions restored and scratch cleaned up.
```

Acquisition succeeded on attempt 2 after ~669 s.

## Included

- `IZCIVSwitch.py` — Lobby injection → loader → engine → bridge → held RPC,
  with live logs, stall detection, `RUN SUMMARY` and `--inspect`.
- `pc-install-trigger.py` — PC-side replacement for Switch 1 +
  `civswitch-ldn-nx.nro`; writes `XSTRIG.Civ7Save` through the original
  `kit/save-tools/restore_save.py`.
- `kit/` — original `civswitch-kit` (engine, bridge, save tools).
- `panel/` — minimal `CivSwitchLDN` + Linux x86_64 runtime for PC-side Lobby
  injection. `prod.keys` is **not** included.
- `izlauncher/` — optional IZlauncher 0.27 menu with an embedded loader
  (double-R3), install/rollback via `install.py`.

## Assets

| Asset | Notes |
|---|---|
| `IZCIVSwitch-0.1.0-linux-x86_64.tar.gz` | Full package; Linux x86_64 + Python 3.14 Lobby runtime |
| `IZCIVSwitch-0.1.0-source.zip` | Scripts + kit + launcher; no Lobby runtime |

## Known limitations

- PC-side Lobby injection is Linux x86_64 only with the bundled runtime.
  Other systems can use the engine with `--no-lobby` after an XSTRIG/S1 install.
- The Switch 1 installer `.nro` is not included; obtain it from the upstream
  kit if you need it.
- `prod.keys` is not included; supply your own dump.
- The FS race remains probabilistic (~30% per boot). The verified run needed
  two acquisition attempts.

## Licensing

GPL-2.0 for this integration. Upstream components retain their licenses; see
`NOTICE.md`, `LICENSE`, `LICENSE-MIT-Gezine.txt`, and the files inside
`izlauncher/package/`.

---

# 旧リリースの記録 — 0.1.0（日本語）

公開日: 2026-11-11

## 実機で確認したこと

PC Lobby経路からの一連の実機試行:

```text
run: switch2-nTDhp6
verified: True
26/26 pipeline stages complete
retainedEndpoint.ready: True
319 496 RPC exchanges
FS execution verified. Original instructions restored and scratch cleaned up.
```

約669秒後、2回目の取得試行で成功。

## 同梱内容

- `IZCIVSwitch.py` — Lobby注入→ローダー→エンジン→ブリッジ→FS RPC保持。
  リアルタイムログ、停滞検出、`RUN SUMMARY`、`--inspect`。
- `pc-install-trigger.py` — Switch 1＋`civswitch-ldn-nx.nro` のPC側代替。
  元キットの `kit/save-tools/restore_save.py` で `XSTRIG.Civ7Save` を書込む。
- `kit/` — 元の `civswitch-kit` エンジン、ブリッジ、セーブツール。
- `panel/` — 最小構成の `CivSwitchLDN` とLinux x86_64用PC Lobbyランタイム。
  `prod.keys` は**同梱しない**。
- `izlauncher/` — 内蔵ローダーを備えた任意のIZlauncher 0.27メニュー。
  R3二度押しで起動し、`install.py` で導入・復元。

## 配布物

| ファイル | 内容 |
|---|---|
| `IZCIVSwitch-0.1.0-linux-x86_64.tar.gz` | Linux x86_64とPython 3.14のLobbyランタイムを含むフル版 |
| `IZCIVSwitch-0.1.0-source.zip` | スクリプト、キット、ランチャー。Lobbyランタイムなし |

## 既知の制限

- 同梱ランタイムのPC Lobby注入はLinux x86_64のみ。他の環境はXSTRIG/Switch 1用
  インストール後、`--no-lobby` でエンジンを使える。
- Switch 1用インストーラーの `.nro` は含まない。必要なら元キットから取得する。
- `prod.keys` は含まない。自分の本体の鍵ダンプを用意する。
- FS競合の成否は確率的で、元キットの概算は起動ごと約30%。
  この検証済み実機runは取得を2回試行した。

## ライセンス

統合部分はGPL-2.0。上流コンポーネントのライセンスはそのまま維持。
`NOTICE.md`、`LICENSE`、`LICENSE-MIT-Gezine.txt`、
`izlauncher/package/` の各ファイルを参照。
