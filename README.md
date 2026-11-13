# IZCIVSwitch

PC-driven filesystem access to Nintendo Switch 2 through *Civilization VII*.

**Documentation version:** `v0.2.0-rc.19` (release candidate)

[English](#english) · [日本語](#日本語) · [Releases](https://github.com/hrvtuirvw/IZCIVSwitch/releases) · [Release notes](RELEASE_NOTES.md)

## English

IZCIVSwitch starts the Civ7 loader from a PC, acquires an FS connection and keeps it available for the current console boot. The `v0.2.0-rc.19` candidate adds system-language commands and bundles [civswitch-kit v1.0.3](https://gitee.com/mza1010/civswitch-kit).

### What this candidate includes

- **PC Lobby injection:** starts the Civ7 loader without requiring the Switch 1 installer NRO.
- **Held FS session:** after both `4/4 verified` and `FS ENDPOINT IS LIVE`, the launcher stays open instead of stopping at the 12-minute acquisition limit.
- **Language inspection and change:** `civ-locale.cjs` checks the live run and language mapping before writing, then saves a PC-side receipt. Restoration is limited to the same live FS session.
- **civswitch-kit v1.0.3:** includes the kit's SD album and FTP tools. FTP is read-only by default; writes require explicit opt-in in both the engine and FTP bridge.
- **Optional XSTRIG loader entry:** starts the loader from Civ7 Load Game on later boots.

### Requirements

The documented PC Lobby setup uses:

| Component | Tested / required for this path |
| --- | --- |
| Console | Switch 2 on firmware **23.0.1** (tested configuration) |
| Game | **Switch 1 physical cartridge**, *Civilization VII* **1.0.0** |
| Network | Wired Ethernet connection to the console; a PC Wi-Fi adapter for Lobby injection |
| PC | **Linux x86_64** for the bundled Lobby runtime; Python 3 and the bundled runtime |
| Language commands | Node.js on the PC |
| Keys | Your own text-format `prod.keys` for PC Lobby mode; **not** needed for an existing-loader `--no-lobby` session |

### Quick start: Linux full package

These instructions use `IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz`. The source ZIP has no bundled PC Lobby runtime; see [Package contents](#package-contents).

**1. Back up your saves, then verify and extract the archive.** From the download directory:

```bash
sha256sum -c --ignore-missing IZCIVSwitch-0.2.0-rc.19-assets.sha256
tar -xzf IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz
cd IZCIVSwitch-0.2.0-rc.19
sha256sum -c SHA256SUMS
```

Work from the extracted, writable directory.

**2. Configure the PC Lobby runtime.** Place your own `prod.keys` at `panel/data/private/civswitchldn/prod.keys`. Then run:

```bash
chmod 700 panel/data/private/civswitchldn
chmod 600 panel/data/private/civswitchldn/prod.keys
sudo setcap cap_net_admin,cap_net_raw=ep panel/data/runtime/civswitchldn/bin/python-ldn
getcap panel/data/runtime/civswitchldn/bin/python-ldn
python3 pc-install-trigger.py --check
```

Confirm `cap_net_admin,cap_net_raw=ep` and `[ok] LDN environment is ready`.

**3. Open the Host Lobby on Switch 2.** In *Civilization VII*, navigate to:

`MULTIPLAYER → WIRELESS → CREATE GAME → HOST LOBBY`

Leave that screen open. On the PC, from the extracted package directory, run:

```bash
python3 IZCIVSwitch.py --lobby --yes
```

**4. Confirm the FS connection.** Wait for **both** messages:

```text
4/4 verified
FS ENDPOINT IS LIVE
```

Keep Civ7 and the launcher running. Copy the `run folder :` path it prints for the language command. A reboot or launcher exit ends this FS session. If acquisition fails, see [Recovery](#recovery-after-a-failed-attempt).

### Language settings in a live FS session

In a **second PC terminal**, switch to the extracted package directory and assign the exact `run folder :` path from the **current** launcher. Do not reuse an older run.

```bash
RUN='/absolute/path/to/current/run'
node civ-locale.cjs inspect "$RUN"
node civ-locale.cjs set "$RUN" --language ko
```

Replace the quoted sample path before running the commands. `inspect` reads the console settings and 20 language mappings without changing the console; it saves an inspection record on the PC. `set` validates the mapping and the live Civ7 run, writes only after those checks pass, and saves a receipt under `RUN/locale/`.

The command offers **17 non-Japanese target languages**:

`ko`, `en-US`, `fr`, `de`, `it`, `es`, `nl`, `pt`, `ru`, `en-GB`, `fr-CA`, `es-419`, `zh-Hans`, `zh-Hant`, `pt-BR`, `pl`, `th`.

`ja` is reserved for restoration. For the receipt and restore command, see [Language settings](docs/MULTILINGUAL.md).

**Do not retry a write if its acknowledgment (ACK) is uncertain.** A confirmed change can be restored from its receipt **only while the same FS session remains live**.

#### Observed behavior

With the earlier Civ7 kit, a `ja` → `ko` write was acknowledged, two readbacks returned `ko`, and System Settings appeared in Korean. After a full reboot, Settings and two read-only checks showed `ja` again. The v1.0.3 kit retains the same post-FS language path.

### Package contents

| File | Contents |
| --- | --- |
| `IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz` | Source, bundled Linux x86_64 PC Lobby runtime and optional launcher |
| `IZCIVSwitch-0.2.0-rc.19-source.zip` | Source and language tools; **no bundled Lobby runtime** |
| `IZCIVSwitch-0.2.0-rc.19-assets.sha256` | SHA-256 checksums for the two downloadable archives |
| `SHA256SUMS` (inside each archive) | Checksums for tracked files after extraction |
| `IZCIVSwitch-0.2.0-rc.19-SHA256.json` | Per-file hashes for tracked package files |

Neither archive includes keys, the Switch 1 installer NRO or personal save backups. Both include these distribution templates:

- `kit/save-tools/trigger-recreate/XSTRIG.Civ7Save`
- `izlauncher/package/IZlauncher-027-FS.Civ7Save`

The bundled Lobby runtime targets **Linux x86_64 / Python 3.14**.

**Using the source ZIP:** Supply a compatible existing `iz2s-panel` and pass the *same* path to preflight and launch:

```bash
PANEL='/absolute/path/to/iz2s-panel/iz2s-platform-run22'
python3 pc-install-trigger.py --panel "$PANEL" --check
python3 IZCIVSwitch.py --lobby --yes --panel "$PANEL"
```

Replace the sample path. Put your keys in **that external panel's** `data/private/civswitchldn/prod.keys` and configure its runtime capabilities. An installed loader can instead use `--no-lobby` without `prod.keys`.

PC Lobby requires your own text-format `prod.keys` with four **32-digit hexadecimal** values: `aes_kek_generation_source`, `aes_key_generation_source`, `master_key_00`, `master_key_12`.

### XSTRIG: loader entry across reboots

XSTRIG lets later boots start the loader from Civ7 **Load Game** instead of repeating PC Lobby injection. Each boot still needs a new FS connection.

With the full-package Lobby runtime configured and **HOST LOBBY** open, install the template once:

```bash
python3 pc-install-trigger.py --yes
```

The installer creates `save:/saves/Single/XSTRIG.Civ7Save` using the kit's restore tool.

Fully power-cycle the console (hold the power button for 12 seconds, wait 5 seconds, then boot). In Civ7, choose **Load Game → XSTRIG.Civ7Save** and wait for `Awaiting payload at <IP>:9026`. In the extracted package directory, enter the IP shown on the console:

```bash
read -r -p 'Switch 2 loader IP: ' CONSOLE_IP
python3 IZCIVSwitch.py --no-lobby --console-ip "$CONSOLE_IP"
```

The installer also prints the `--no-lobby` command.

### Monitoring and optional tools

Use the **current** run folder without launching another engine:

```bash
RUN='/absolute/path/to/current/run'
python3 IZCIVSwitch.py --inspect "$RUN"
node kit/port/engine/rpc.cjs "$RUN" status
```

`status` may respond at `2/4`; that alone does **not** establish FS access. The required confirmation remains `4/4 verified` **and** `FS ENDPOINT IS LIVE`.

The current attempt log is listed in `RUN/switch2/acquisition-supervisor.json`; the launcher ends with `RUN SUMMARY`.

For the optional menu-based loader, see [IZlauncher](izlauncher/README.md).

### Recovery after a failed attempt

A failed run may leave temporary data in `save:/`. Keep its run folder and do not manually retry on the same console boot. Before another attempt, compare the run's created paths with its cleanup record; handle only proven run-owned leftovers on a separate full boot. See the [safety notice](DISCLAIMER.md).

### Credits and licenses

The integration is [GPL-2.0](LICENSE). Bundled projects retain their licenses and attributions; see [NOTICE.md](NOTICE.md).

---

## 日本語

IZCIVSwitchは、PCから『Civilization VII』（Civ7）のローダーを起動し、Switch 2のファイルシステム（FS）へ接続するツール。取得したFS接続は、本体の現在の起動中に限って維持できる。`v0.2.0-rc.19` では言語設定コマンドを追加し、[civswitch-kit v1.0.3](https://gitee.com/mza1010/civswitch-kit)を取り込んだ。

### 今回の主な機能

- **PC Lobby経由のローダー起動:** Switch 1用インストーラーNROを使わず、PCからCiv7のローダーを起動する。
- **FS接続の維持:** `4/4 verified` と `FS ENDPOINT IS LIVE` の両方を確認した後は、従来の12分の取得制限でランチャーが自動終了しない。
- **本体言語の確認・変更:** `civ-locale.cjs` が現在のrunと言語対応表を検証してから書き込み、PC側に記録を残す。復元できるのは同じFS接続中だけ。
- **civswitch-kit v1.0.3:** SDアルバムとFTPツールを含む。FTPは初期状態で読取り専用。書込みにはエンジンとFTPブリッジの両方で許可が必要。
- **XSTRIG（任意）:** 次回以降にCiv7のLoad Gameからローダーを起動できる。

### 動作環境

PC Lobbyを使う場合の構成は以下のとおり。

| 項目 | 確認済み構成・必要なもの |
| --- | --- |
| 本体 | Switch 2、ファームウェア **23.0.1**（確認に使用した環境） |
| ゲーム | **Switch 1版の物理カートリッジ**『Civilization VII』**1.0.0** |
| ネットワーク | Switch 2への有線Ethernet接続、Lobby用のPC側Wi-Fiアダプター |
| PC | 同梱Lobbyランタイムを使う場合は **Linux x86_64**。Python 3と同梱ランタイム |
| 言語コマンド | PC側のNode.js |
| 鍵 | PC Lobbyでは自分のテキスト形式の `prod.keys`。既存ローダーの `--no-lobby` では不要 |

### クイックスタート：Linuxフル版

以下は `IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz` を使った手順。ソースZIPにはPC Lobbyランタイムが含まれないため、[配布ファイル](#配布ファイル)を参照。

**1. セーブをバックアップし、アーカイブを検証して展開する。** ダウンロードしたファイルのあるディレクトリで実行する。

```bash
sha256sum -c --ignore-missing IZCIVSwitch-0.2.0-rc.19-assets.sha256
tar -xzf IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz
cd IZCIVSwitch-0.2.0-rc.19
sha256sum -c SHA256SUMS
```

展開後は書込み可能なディレクトリで作業する。

**2. PC Lobbyランタイムを準備する。** 自分の `prod.keys` を `panel/data/private/civswitchldn/prod.keys` に置き、以下を実行する。

```bash
chmod 700 panel/data/private/civswitchldn
chmod 600 panel/data/private/civswitchldn/prod.keys
sudo setcap cap_net_admin,cap_net_raw=ep panel/data/runtime/civswitchldn/bin/python-ldn
getcap panel/data/runtime/civswitchldn/bin/python-ldn
python3 pc-install-trigger.py --check
```

`cap_net_admin,cap_net_raw=ep` と `[ok] LDN environment is ready` を確認する。

**3. Switch 2でHost Lobbyを開く。** 『Civilization VII』で次の画面へ進み、そのままにする。

`MULTIPLAYER → WIRELESS → CREATE GAME → HOST LOBBY`

PC側で、展開先のディレクトリから実行する。

```bash
python3 IZCIVSwitch.py --lobby --yes
```

**4. FS接続を確認する。** 以下の**両方**が表示されるまで待つ。

```text
4/4 verified
FS ENDPOINT IS LIVE
```

Civ7とランチャーを動かしたまま、表示された `run folder :` のパスを言語コマンドに使う。ランチャー終了や本体再起動でこのFS接続は切れる。取得に失敗した場合は[失敗後の対応](#失敗後の対応)へ。

### FS接続中の言語設定

展開先で**別のPC端末**を開き、今回のランチャーに表示された `run folder :` のパスを指定する。過去のrunを指定しないこと。

```bash
RUN='/absolute/path/to/current/run'
node civ-locale.cjs inspect "$RUN"
node civ-locale.cjs set "$RUN" --language ko
```

`RUN` の値は**実際のパスに置き換える**。`inspect` は本体設定を変更せず、現在の設定と言語対応20件を読み、PCに確認記録を残す。`set` は対応表と現在のCiv7 runを検証し、条件を満たした場合だけ書き込む。書込み記録は `RUN/locale/` に保存される。

日本語以外の**17言語**から選べる。

`ko`、`en-US`、`fr`、`de`、`it`、`es`、`nl`、`pt`、`ru`、`en-GB`、`fr-CA`、`es-419`、`zh-Hans`、`zh-Hant`、`pt-BR`、`pl`、`th`。

`ja` は復元用。記録と復元コマンドは[言語設定手順](docs/MULTILINGUAL.md)を参照。

**ACK（応答）の成否が不明な書込みは再送しない。** 正常な変更であっても、記録を使った復元ができるのは**同じFS接続が続いている間だけ**。

#### 確認した動作

以前のCiv7キットでは、`ja` → `ko` の書込みにACKが返り、2回の読戻しで `ko`、本体設定画面で韓国語を確認した。フル再起動後は、設定画面と2回の読取り専用確認が `ja` に戻った。v1.0.3でもFS取得後の言語処理経路は同じ。

### 配布ファイル

| ファイル | 内容 |
| --- | --- |
| `IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz` | ソース一式、Linux x86_64用PC Lobbyランタイム、任意のランチャー |
| `IZCIVSwitch-0.2.0-rc.19-source.zip` | ソースと言語ツール。**PC Lobbyランタイムは含まない** |
| `IZCIVSwitch-0.2.0-rc.19-assets.sha256` | 配布アーカイブ2点のSHA-256 |
| 各アーカイブ内の `SHA256SUMS` | 展開後の追跡対象ファイルのSHA-256 |
| `IZCIVSwitch-0.2.0-rc.19-SHA256.json` | 追跡対象ファイルごとのハッシュ一覧 |

鍵、Switch 1用インストーラーNRO、個人のセーブバックアップは含まれない。次の配布用テンプレートは含まれる。

- `kit/save-tools/trigger-recreate/XSTRIG.Civ7Save`
- `izlauncher/package/IZlauncher-027-FS.Civ7Save`

同梱のLobbyランタイムは **Linux x86_64 / Python 3.14** 向け。

**ソースZIPでPC Lobbyを使う場合:** 互換性のある既存の `iz2s-panel` を用意し、事前確認と起動の両方で**同じパス**を指定する。

```bash
PANEL='/absolute/path/to/iz2s-panel/iz2s-platform-run22'
python3 pc-install-trigger.py --panel "$PANEL" --check
python3 IZCIVSwitch.py --lobby --yes --panel "$PANEL"
```

`PANEL` は実際のパスに変更する。鍵は**その外部パネル側**の `data/private/civswitchldn/prod.keys` に置き、ランタイムのcapabilityを設定する。導入済みローダーなら `--no-lobby` を使え、`prod.keys` は不要。

PC Lobbyには自分のテキスト形式の `prod.keys` が必要。`aes_kek_generation_source`、`aes_key_generation_source`、`master_key_00`、`master_key_12` の4項目はいずれも**32桁の16進数**。

### XSTRIG：再起動後も使えるローダー入口

XSTRIGを使うと、次回以降はCiv7の **Load Game** からローダーを起動できる。FS接続は起動ごとに取り直す。

フル版のPC Lobbyランタイムを準備し、Switch 2で **HOST LOBBY** を開いた状態で一度だけ導入する。

```bash
python3 pc-install-trigger.py --yes
```

インストーラーは元キットの復元ツールで `save:/saves/Single/XSTRIG.Civ7Save` を作る。

本体の電源ボタンを12秒押して完全終了し、5秒待ってから起動する。Civ7で **Load Game → XSTRIG.Civ7Save** を選び、`Awaiting payload at <IP>:9026` と表示されるまで待つ。PC側では、画面に表示されたIPアドレスを入力して実行する。

```bash
read -r -p 'Switch 2 loader IP: ' CONSOLE_IP
python3 IZCIVSwitch.py --no-lobby --console-ip "$CONSOLE_IP"
```

インストーラーにも `--no-lobby` コマンドが表示される。

### 状態確認と任意のツール

**現在のrun**のパスを使い、別のエンジンを起動せず状態を確認できる。

```bash
RUN='/absolute/path/to/current/run'
python3 IZCIVSwitch.py --inspect "$RUN"
node kit/port/engine/rpc.cjs "$RUN" status
```

`2/4` の段階でも `status` は応答するため、**応答しただけではFS取得成功ではない**。成功判定には `4/4 verified` と `FS ENDPOINT IS LIVE` の両方が必要。

進行中のログは `RUN/switch2/acquisition-supervisor.json` で確認できる。ランチャーの最後には `RUN SUMMARY` が出る。

任意のメニュー型ローダーは[IZlauncherの手順](izlauncher/README.md)を参照。

### 失敗後の対応

失敗したrunのフォルダーを残し、同じ本体起動中に手動で再実行しない。`save:/` に残った一時データは、そのrunが作成したパスと片付け記録を照合し、別のフル起動後に所有を確認できたものだけ処理する。詳しくは[安全上の注意](DISCLAIMER.md)へ。

### クレジットとライセンス

統合部分は[GPL-2.0](LICENSE)。同梱物それぞれのライセンスと出典は[NOTICE.md](NOTICE.md)を参照。
