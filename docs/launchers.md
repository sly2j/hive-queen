# Launchers

A launcher is a named launch command, optionally with its own Claude config dir. The registry is the `[[launchers]]` list in `config.toml`; `[defaults] launcher` names the default for new types. `hive launchers` lists the registry plus the `[queen] discover` records. The registry wins on a name in both, and the discover record is then marked `shadowed=yes`. If `discover` is unset it adds nothing; if it fails, the registry is still listed, followed by a `discover error=<reason>` line (exit 0). Use one with `hive spawn --launcher NAME`. Add one with `hive launchers add` and change the default with `hive launchers default`; check the command first with `hive inspect-launcher "CMD"` to infer its `config_dir`. To rename or remove a launcher, edit `config.toml` by hand.

Command details: [hive launchers](commands.md), [hive spawn](commands.md#hive-spawn), [hive inspect-launcher](commands.md#hive-inspect-launcher).
