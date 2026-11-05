// Windows' npm and pnpm are .cmd shims, and a child .cmd can only be run through the
// shell (execFileSync refuses batch files without it since Node's CVE-2024-27980 fix).
// Through the shell, cmd.exe splits an unquoted argument at its spaces: a staging
// directory under a user name like "John Doe" reached `pnpm pack` as two arguments and
// the staging failed with "pnpm pack left no tarball". Arguments with spaces are quoted,
// so each stays the one argument the caller passed.
export function shellArgs(argv) {
  return argv.map((arg) => (/\s/.test(arg) ? `"${arg}"` : arg));
}
