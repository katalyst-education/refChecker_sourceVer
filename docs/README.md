# RefChecker documentation

RefChecker exposes one shared verification engine through the Web UI, desktop app, CLI, and HTTP API.

- [Feature overview](FEATURES.md)
- [Web UI and API guide](web-ui.md)
- [Design system](design.md)
- [Project README](../README.md)
- [Technical paper](../paper/paper.md)

The shared core owns extraction, source lookup, metadata comparison, verdicts, and reporting. Surface-specific code is limited to input, transport, orchestration, and presentation.

