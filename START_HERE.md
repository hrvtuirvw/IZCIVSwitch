# Start here / 最初に読む

[English](#english) · [日本語](#日本語)

## English

These steps are for the **Linux x86_64 full archive** and PC Lobby mode. The
[source ZIP](README.md#package-contents) needs a compatible external `--panel` for Lobby mode.

1. Back up your saves. Verify `IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz` against
   `IZCIVSwitch-0.2.0-rc.19-assets.sha256` in the download directory, then extract the whole
   archive into a writable folder and enter `IZCIVSwitch-0.2.0-rc.19`.
2. Put your own text `prod.keys` in `panel/data/private/civswitchldn/prod.keys` (not supplied).
   Prepare and check the runtime:

   ```bash
   chmod 700 panel/data/private/civswitchldn
   chmod 600 panel/data/private/civswitchldn/prod.keys
   sudo setcap cap_net_admin,cap_net_raw=ep panel/data/runtime/civswitchldn/bin/python-ldn
   getcap panel/data/runtime/civswitchldn/bin/python-ldn
   python3 pc-install-trigger.py --check
   ```

   Expect `cap_net_admin,cap_net_raw=ep` and `[ok] LDN environment is ready`.
3. On Switch 2, open **Civ7 → MULTIPLAYER → WIRELESS → CREATE GAME → HOST LOBBY**. On the PC:
   `python3 IZCIVSwitch.py --lobby --yes`.
4. Wait for **both** `4/4 verified` and `FS ENDPOINT IS LIVE`. Keep the game and launcher running.
   Copy the **current** `run folder :` path printed by the launcher into a second terminal:

   ```bash
   RUN='/absolute/path/to/current/run'
   node civ-locale.cjs inspect "$RUN"
   node civ-locale.cjs set "$RUN" --language ko
   ```

   Replace the sample path with the current run path. For other languages and restoration, read [Language settings](docs/MULTILINGUAL.md).

If acquisition fails, follow [Recovery](README.md#recovery-after-a-failed-attempt).

---

## 日本語

以下は**Linux x86_64フル版**でPCからLobbyへ注入する手順。
[ソースZIP](README.md#配布ファイル)でLobbyを使う場合は互換性のある外部 `--panel` が必要。

1. 先にセーブをバックアップ。ダウンロード先で `IZCIVSwitch-0.2.0-rc.19-linux-x86_64.tar.gz` を
   `IZCIVSwitch-0.2.0-rc.19-assets.sha256` と照合してから、アーカイブを丸ごと書込み可能なフォルダーに展開し、
   `IZCIVSwitch-0.2.0-rc.19` に入る。
2. 自分のテキスト形式の `prod.keys` を `panel/data/private/civswitchldn/prod.keys` に置く（同梱なし）。
   ランタイムを準備・確認する。

   ```bash
   chmod 700 panel/data/private/civswitchldn
   chmod 600 panel/data/private/civswitchldn/prod.keys
   sudo setcap cap_net_admin,cap_net_raw=ep panel/data/runtime/civswitchldn/bin/python-ldn
   getcap panel/data/runtime/civswitchldn/bin/python-ldn
   python3 pc-install-trigger.py --check
   ```

   `cap_net_admin,cap_net_raw=ep` と `[ok] LDN environment is ready` を確認。
3. Switch 2で **Civ7 → MULTIPLAYER → WIRELESS → CREATE GAME → HOST LOBBY** を開く。
   PCで `python3 IZCIVSwitch.py --lobby --yes` を実行。
4. **`4/4 verified` と `FS ENDPOINT IS LIVE` の両方**を待つ。
   ゲームとランチャーを止めず、表示された**今回の** `run folder :` のパスを別端末の `RUN` に指定する。

   ```bash
   RUN='/absolute/path/to/current/run'
   node civ-locale.cjs inspect "$RUN"
   node civ-locale.cjs set "$RUN" --language ko
   ```

   `RUN` に今回のパスを入れる。ほかの言語と復元は[言語設定手順](docs/MULTILINGUAL.md)へ。

FS取得に失敗した場合は[失敗後の対応](README.md#失敗後の対応)へ。
