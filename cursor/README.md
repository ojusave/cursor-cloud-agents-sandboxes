# Cursor helpers

Follow the [repository walkthrough](../README.md) from the repository root.
The shared [fixture](../fixture), [prompt](../prompt.txt), and [verifier](../verify.mjs)
are used by both [Python](python) and [TypeScript](typescript) helpers.

The [controller](controller/spawn.sh) creates one sandbox for each claim and passes
only that claim's token to the worker. API keys remain on the controller or helper host.
A complete live Cursor run is still unverified; see [validation status](../README.md#validation-status).
