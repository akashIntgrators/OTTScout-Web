# Sony India verification relay: rollout review

This is a proposed rollout, not an instruction that setup has occurred. The VPS
is trusted to report the Sony HTTPS responses it sees; SSH authenticates the
VPS but cannot independently prove what Sony returned. The existing discovery
checks still require Sony's exact `India` region, exact title identity, India
availability and release evidence. No paid API credentials or requests belong
on the VPS. Automatic checks remain subject to Sony's robots policy.

The relay enforces an exclusive lock and a persistent limit of 12 actual
public GETs in any rolling six-hour window, including robots, redirects and failed
requests. Scheduled runs may be delayed, and a run within six hours of earlier requests can
encounter the cap; a failed or partial scan does not renew existing records.
The relay currently rejects redirects to any different URL. Whether live Sony
pages follow those restrictions has not yet been verified through this relay.

## Before changing anything

Review the server's distribution, Python executable, existing SSH settings,
active access paths and verified host key. Preserve existing administrator
access and confirm there is an independent recovery path before reloading SSH.
Use a dedicated system account whose home, SSH configuration, public key and
code are owned by root. Its writable private ledger directory must survive
reboots and must not be cleaned automatically. Confirm SSH effective settings
with `sshd -t` and `sshd -T -C` for the dedicated account before reload. The
proposed `Match User` settings below must coexist with the actual server's
existing configuration and include order. Do not replace the server's SSH
configuration wholesale.

An Ubuntu/Debian-style setup would use the following **reviewed values**,
adjusting only after checking the server:

* Account `ottscout-sony`, with `/bin/sh` as its login shell (a `nologin` shell
  also blocks forced commands on common OpenSSH configurations).
* Root-owned non-writable code directory `/usr/local/libexec/ottscout-sony`;
  install this change's `scripts/sony_india_relay.py` and
  `scripts/official_discovery.py` there with owner `root:root`, mode `0644`.
* Root-owned `/etc/ssh/authorized_keys/ottscout-sony`, mode `0644`, containing
  only the newly generated dedicated public key with `restrict` and an
  explicit forced command. No other key or authentication path for this user.
* `/var/lib/ottscout-sony` owned by `ottscout-sony`, mode `0700`, for the
  persistent `ledger.json` only; the relay creates it with mode `0600`.
* System Python at the independently verified absolute path, represented here
  as `/usr/bin/python3`. Only Python standard-library modules are needed.

A suitable public-key entry, after substituting the dedicated public key, is:

```text
restrict,command="/usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/python3 -s -E /usr/local/libexec/ottscout-sony/sony_india_relay.py /var/lib/ottscout-sony/ledger.json" ssh-ed25519 PUBLIC_KEY_MATERIAL ottscout-sony
```

Defense-in-depth SSH settings for the dedicated account:

```text
Match User ottscout-sony
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    ForceCommand /usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/python3 -s -E /usr/local/libexec/ottscout-sony/sony_india_relay.py /var/lib/ottscout-sony/ledger.json
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthenticationMethods publickey
    PermitUserEnvironment no
    PermitTTY no
    AllowAgentForwarding no
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
```

Create a **new dedicated** Ed25519 key pair locally, with the private key in a
private temporary directory; never reuse an administrator key or log its
contents. Install only the public key on the server. Pin the already verified
host key in a known-hosts entry for the exact host and port; do not establish
trust from an unauthenticated `ssh-keyscan`. The private key permits only this
restricted relay, but its disclosure would still allow attempts against the
public-request cap, so it must be treated as a secret.

## GitHub configuration and verification

On the `github-pages` environment for this repository, set these environment
secrets through GitHub's secret UI or authenticated CLI without printing them:

* `SONY_RELAY_HOST`: exact SSH destination, e.g. `ottscout-sony@host`.
* `SONY_RELAY_PRIVATE_KEY`: contents of the new dedicated private key.
* `SONY_RELAY_KNOWN_HOSTS`: pinned OpenSSH known-hosts entry.

The workflow currently uses SSH port 22; a different port needs a reviewed
change before enabling. Once all three secrets are present and the SSH account
is independently verified as restricted, set the environment variable
`SONY_RELAY_ENABLED` to `true`. The variable is the activation switch: if
it is true and any secret is absent, the discovery step fails rather than
falling back to another location. The workflow's job runs only on main.

Run the main-branch workflow with `offline_only=true` to avoid movie-provider
and metadata API calls. The first live check is bounded by the relay's limit.
Inspect the sanitized source statuses and health report, and the VPS ledger
count, without printing raw HTML, credentials, host details or private data.
An actual Sony response still must pass all existing evidence checks; an India
index alone does not guarantee any title is publishable. If the check fails,
leave previous evidence at its original expiry and investigate; do not label
verification healthy merely because the VPS is reachable.

Disable the switch to stop use of the relay; remove the dedicated authorized
key and environment secrets when retiring it. Keep the ledger until the relay is
disabled so a restart cannot reset the request cap.
