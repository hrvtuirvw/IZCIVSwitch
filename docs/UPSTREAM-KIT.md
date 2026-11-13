# Upstream kit / 元キットについて

[English](#english) · [日本語](#日本語)

## English

The v0.2.0-rc.19 candidate includes the **tracked kit files** of
[mza1010/civswitch-kit](https://gitee.com/mza1010/civswitch-kit) Gitee tag `v1.0.3`, commit
`5410c7ffd61aebc103d988c762a9af785213c64b` (2026-11-13 +08:00). All **216 included tracked kit files**, including distribution templates, match the pinned
checkout byte for byte under `kit/`. The third-party
`switch1/civswitch-ldn-nx.nro` is **not included**. Upstream removed the obsolete
`docs/PORT-HANDOFF.md`; this package does not restore it. The upstream `kit/NOTICE.md` refers to
upstream's full kit, including that NRO, rather than the contents of this repack.

The original [byizmysh/IZCIVSwitch](https://github.com/byizmysh/IZCIVSwitch) GitHub main was
`fed431f335670e16169c77ba3cfd5c4a505a69fd` when this candidate was prepared and had not yet
integrated this kit update. Compared with the earlier bundled kit, v1.0.3 adds GUI/SD album/FTP code
and changes some FS acquisition and retained-session commands. It also adds documentation. Our
`run-fs.py` monitor follows v1.0.3's **live per-attempt log** through `acquisition-supervisor.json`;
`acquisition.log` is a compatibility copy produced after an attempt fails. The PC launcher's
12-minute limit still applies to acquisition, but not after verified 4/4.

The **language operation after FS acquisition** is unchanged: `port/engine/run.cjs`,
`switch2/tools/fs-memory.cjs`, `switch2/ro/test-sm.cjs`, `switch2/memory/fs-memory-control.cjs` and
the supporting RO runtime/objects match the older kit byte for byte. The `ro/control.cjs` changes
add SD dispatch and a borrowed-handle `any:true` option; the locale helper uses neither, and its
normal IPC/service branch is unchanged. The older v0.1.0 release was not modified.

The earlier-kit Civ7 session that showed Korean System Settings used this same post-FS language
path. v1.0.3 also adds upstream SD album/FTP tools; see its CHANGELOG for that kit's own results.
`kit/port/engine/rpc.cjs stop` releases a held session: do not invoke it if you intend to keep FS
available. SD writes require both `NS2_ALLOW_WRITES=1` in the engine and `--allow-write` in the FTP
bridge; otherwise FTP is read-only. See [kit CHANGELOG](../kit/CHANGELOG.md) and
[FTP guide](../kit/tools/sd-ftp/README.md) (upstream documentation is in Chinese).

---

## 日本語

v0.2.0-rc.19候補には、[mza1010/civswitch-kit](https://gitee.com/mza1010/civswitch-kit)のGiteeタグ `v1.0.3`、コミット `5410c7ffd61aebc103d988c762a9af785213c64b`（2026-11-13 +08:00）の**追跡対象ファイル**を入れた。
取り込んだキットの追跡対象**216ファイル**（配布用テンプレートを含む）は、固定した元キットのcheckoutと `kit/` 以下でバイト一致。
第三者製の `switch1/civswitch-ldn-nx.nro` は**含まない**。
元キットが削除した古い `docs/PORT-HANDOFF.md` も復活させていない。
`kit/NOTICE.md` がNROに言及するのは元キットの全体構成であり、この再梱包物の中身ではない。

この候補の準備時点で、元の[byizmysh/IZCIVSwitch](https://github.com/byizmysh/IZCIVSwitch)のGitHub mainは `fed431f335670e16169c77ba3cfd5c4a505a69fd` で、今回のキット更新は未取込みだった。
以前の同梱キットに比べ、v1.0.3はGUI・SDアルバム・FTPのコード、FS取得と接続保持の一部コマンド、文書を更新している。
こちらの `run-fs.py` モニターは `acquisition-supervisor.json` が示す**現在の試行ログ**を読む。
`acquisition.log` は試行失敗後に作られる互換用コピー。
PCランチャーの12分制限はFS取得中だけに適用し、4/4で確認した接続は自動で終了しない。

**FS取得後の言語操作**に使う `port/engine/run.cjs`、`switch2/tools/fs-memory.cjs`、`switch2/ro/test-sm.cjs`、`switch2/memory/fs-memory-control.cjs` と対応するROランタイム・オブジェクトは、以前のキットとバイト一致。
`ro/control.cjs` の差分はSDへの振分けと借用ハンドルの `any:true` オプションで、言語コマンドはどちらも使わない。
通常のIPC・サービス分岐は同じ。
旧v0.1.0の公開物は変更していない。

以前のCiv7キットで韓国語の本体設定画面を確認したrunは、この同じFS取得後の言語経路を使った。
v1.0.3で加わったSDアルバム・FTPツールの詳細は元キットのCHANGELOGを参照。
`kit/port/engine/rpc.cjs stop` はFS保持を解除するため、接続を使い続ける場合は実行しない。
SD書込みにはエンジン側の `NS2_ALLOW_WRITES=1` とFTPブリッジ側の `--allow-write` の両方が必要で、通常は読取り専用。
詳しくは[キットのCHANGELOG](../kit/CHANGELOG.md)と[FTP手順](../kit/tools/sd-ftp/README.md)（元の文書は中国語）を参照。
