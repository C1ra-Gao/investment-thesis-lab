# Environment name and precedence audit

Audited 2026-10-14. No model or financial request is made by configuration checks.
Do not use `env`, `printenv`, expanded `docker compose config`, or `docker inspect`
output to report secret configuration: these can expose actual credentials.

## Backend and template agree

| Purpose | Actual backend name | .env.example |
| --- | --- | --- |
| Model Provider | THESISLAB_LLM_PROVIDER | Same |
| Model name | THESISLAB_LLM_MODEL | Same |
| Model secret | THESISLAB_LLM_API_KEY | Same, blank |
| Financial Provider | THESISLAB_FINANCIAL_PROVIDER | Same |
| Financial secret | THESISLAB_FINANCIAL_API_KEY | Same, blank |

`ProviderSettings.from_environment` reads these exact names through
`read_environment`; it does not use OPENAI_API_KEY or DEEPSEEK_API_KEY for the
Agent workspace. The latter remains a documented legacy M2.5 CLI setting only.
Web API exposes configuration booleans; neither model/financial key nor SEC
contact address is returned.

## Direct Python

Load order is the project `.env`, then actual process environment. A process
variable **even if empty** overrides the file. Run from the repository root;
restart the service after editing `.env`. The reader does not run shell commands
or substitute `$VARIABLE` expressions. Quoted values are unquoted.

## Current Compose

`workspace.env_file` explicitly references `.env`. There is no `environment`
mapping overriding the model/financial names, no interpolation of those names in
compose.yaml and no corresponding image ENV/ARG. Therefore the current ordinary
`docker compose up` puts the env_file values in the container environment, which
the backend reads. Host-shell variables are **not automatically substituted** for
the explicit env_file assignments in this configuration.

For this non-interpolated setup the applicable priority is an explicit
`docker compose run -e` override, then Compose `environment` if added, then
`env_file`, then image ENV. Interpolation/pass-through has additional precedence
rules; see [Docker's official reference](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/).
The Compose auto-read `.env` used for `${...}` substitution and a service env_file
have different roles; [env_file reference](https://docs.docker.com/reference/compose-file/services/#env_file).
Default env_file parsing can interpolate `$` in unquoted/double-quoted values;
use single-quoted literal credentials if they contain `$`, and do not enter
command substitution. No key values should be passed as CLI arguments.

After changing the file use `docker compose up -d --force-recreate`; plain restart
does not reload env_file. Docker is not installed on the current host, so the
container-effective configuration has not been runtime-verified here. Static
source and Python precedence tests were checked; no expanded secret output was
generated.

## Safe status check

From repo root: `.venv/bin/python tools/check_provider_config.py`. It emits only
Provider/model metadata, key-present booleans and overriding variable **names**;
no network request or key value. Current check found a configured model key, but
that does not establish authentication, billing balance or network availability.
Presence of a financial key does not authorize this acceptance run to query it.

The human requires explicit “configuration complete, start real model acceptance”
notification before the separately authorized maximum of 14 model requests.
Financial paid queries remain outside that authorization. The bounded acceptance
runner only permits Understand/Plan requests and does not invoke Execute.

The human explicitly authorized starting and updated the credential. The bounded
run has now consumed all 14 actual requests; no further acceptance calls are
authorized under this budget. See MVP-ACCEPTANCE.md for usage and limitations.
