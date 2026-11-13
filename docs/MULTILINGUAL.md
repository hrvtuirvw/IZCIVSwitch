# Language settings during a Civ7 FS session / Civ7のFS接続中の言語設定

[English](#english) · [日本語](#日本語)

## English

This command works **only while a verified Civ7 FS session is live on the current boot**. It neither
starts the console nor acquires FS. These instructions target the observed Switch 2 firmware
**23.0.1** and Switch 1 Civ7 physical cart **1.0.0**. rc.19 includes civswitch-kit
v1.0.3.

Start `python3 IZCIVSwitch.py --lobby --yes` (or use `--no-lobby` if a loader is already installed).
Wait for **both** `4/4 verified` and `FS ENDPOINT IS LIVE`. Keep the game and launcher running. In a
**second terminal**, copy the path printed after `run folder :` into `RUN` below. The assignment
value is an example placeholder; use the path from **this** launcher, not a previous run:

```bash
RUN='/paste/the/run-folder-path/shown/by/the/launcher'
node civ-locale.cjs --help
node civ-locale.cjs inspect "$RUN"
node civ-locale.cjs set "$RUN" --language ko
# Only after a successful set, and only before this FS session ends:
node civ-locale.cjs restore "$RUN" \
  --journal "$RUN/locale/set-$(basename "$RUN").json"
```

`inspect` reads RegionCode, LanguageCode and all 20 `MakeLanguageCode` results for this boot. It
records an inspection receipt **on the PC**, but does **not** change console settings. `set`
verifies the current mapping and retained FS run, changes RegionCode from 0 to 1 only if required,
writes the chosen language and reads it back. It refuses writes if the region is not 0/1, the
mapping differs, or the run and live session do not match. The successful set receipt is
`RUN/locale/set-<actual-run-name>.json`.

`restore` requires that exact set receipt, the **same live FS session**, and settings that still
match the successful write. It restores the original language and RegionCode (including an original
region 0). Neither set nor restore receipt may be reused. If a setter acknowledgement is uncertain,
**do not repeat the command**; preserve the receipts and stop.

The 17 target languages are `en-US`, `fr`, `de`, `it`, `es`, `ko`, `nl`, `pt`, `ru`, `en-GB`,
`fr-CA`, `es-419`, `zh-Hans`, `zh-Hant`, `pt-BR`, `pl`, `th`. `ja` is for restoration only. The
observed 20-entry mapping includes `0=ja`, `1=en-US`, `6=ko`, `7=nl`, `16=pl`, `17=th`, `18=ja`,
`19=en-US`: do **not** use the older `7=ko` assumption. The command checks all 20 entries each time.

With the earlier Civ7 kit, a `ja`→`ko` write was acknowledged, two readbacks returned `ko`, and
System Settings appeared in Korean. After a full reboot, Settings and two read-only checks showed
`ja` again. The [post-FS language route](UPSTREAM-KIT.md) is unchanged in v1.0.3.

The 12-minute deadline applies to acquisition; a verified session lasts until the launcher, game
or console stops. For failed acquisition, see [Recovery](../README.md#recovery-after-a-failed-attempt).

---

## 日本語

このコマンドが使えるのは、**今回の起動で確認済みのCiv7 FS接続を保持している間だけ**。
本体の起動やFS取得は行わない。
確認した環境はSwitch 2 **FW 23.0.1**、Switch 1版Civ7物理カート **1.0.0**。
rc.19にはcivswitch-kit v1.0.3を同梱する。

`python3 IZCIVSwitch.py --lobby --yes` を起動（ローダー導入済みなら `--no-lobby`）。**`4/4 verified` と `FS ENDPOINT IS LIVE` の両方**を待つ。
ゲームとランチャーを動かしたまま、**別の端末**で `run folder :` の後に表示されたパスを以下の `RUN` に入れる。
代入値は例のプレースホルダー。**今回**表示されたパスを使い、以前のrunは使わない。

```bash
RUN='/paste/the/run-folder-path/shown/by/the/launcher'
node civ-locale.cjs --help
node civ-locale.cjs inspect "$RUN"
node civ-locale.cjs set "$RUN" --language ko
# setが成功した後、同じFS接続が終わる前だけ:
node civ-locale.cjs restore "$RUN" \
  --journal "$RUN/locale/set-$(basename "$RUN").json"
```

`inspect` は今回の起動のRegionCode、LanguageCode、`MakeLanguageCode` 20件を読む。**PC側**に確認記録を残すが、**本体設定は変更しない**。
`set` は現在の対応表とFS接続中のrunを確認してから、必要な場合のみ地域値を0から1へ変更し、選んだ言語を書いて読戻す。
地域値が0/1以外、対応表が違う、現在の接続とrunが一致しない場合は書き込まない。
成功時の記録は `RUN/locale/set-<実際のrun名>.json`。

`restore` にはその記録と**同じFS接続**が必要。
設定が成功時の書込み後の値のままなら、元の言語と地域値（元が0なら0）へ戻す。
set/restoreの記録は再利用できない。
setterのACKが不明なときは**再実行せず**、記録を保全して止める。

選べる17言語は `en-US`、`fr`、`de`、`it`、`es`、`ko`、`nl`、`pt`、`ru`、`en-GB`、`fr-CA`、`es-419`、`zh-Hans`、`zh-Hant`、`pt-BR`、`pl`、`th`。
`ja` は復元専用。
実測した20件の対応には `0=ja`、`1=en-US`、`6=ko`、`7=nl`、`16=pl`、`17=th`、`18=ja`、`19=en-US` がある。
古い `7=ko` は使わず、コマンドが毎回20件を照合する。

以前のCiv7キットでは、`ja`→`ko` の書込みにACKが返り、2回の読戻しで `ko`、本体設定画面で韓国語を確認した。
フル再起動後は、設定画面と2回の読取りで `ja` に戻った。[FS取得後の言語経路](UPSTREAM-KIT.md)はv1.0.3でも同じ。

12分の制限はFS取得中だけ。ランチャー・ゲームの終了や本体再起動で接続は終わる。取得に失敗した場合は[失敗後の対応](../README.md#失敗後の対応)へ。
