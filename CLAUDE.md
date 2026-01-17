# Philips AirPurifier CoAP - Claude Code Guidelines

## Project Overview
Home Assistant custom integration for Philips Air Purifiers using CoAP protocol.

## Project Structure
```
custom_components/philips_airpurifier_coap/
├── devices/          # Device classes (base, legacy, new_gen, new2_gen)
├── translations/     # i18n files (en, fr, de, nl, bg, ro, sk)
├── __init__.py       # Integration setup
├── config_flow.py    # Config flow with network scan
├── coordinator.py    # Data coordinator
├── const.py          # Constants and device definitions
└── [platform].py     # Entity platforms (fan, sensor, switch, etc.)
```

## Commands
```bash
# Lint
ruff check custom_components/philips_airpurifier_coap/

# Format
ruff format custom_components/philips_airpurifier_coap/

# Test
pytest tests/

# Syntax check
python3 -m py_compile custom_components/philips_airpurifier_coap/*.py
```

## Development
- Deploy to test HA: `sudo cp -r custom_components/philips_airpurifier_coap/* /home/stephane/homeassistant/config/custom_components/philips_airpurifier_coap/`
- Restart HA: `docker restart homeassistant`
- Check logs: `docker logs homeassistant --tail 100`

## Code Style
- Python 3.11+ target
- Max line length: 100
- Max cyclomatic complexity: 10
- Use type hints
- Follow Home Assistant coding guidelines

## Commits
- Ne jamais ajouter "Co-Authored-By" dans les messages de commit
- Utiliser des messages de commit conventionnels (feat:, fix:, chore:, refactor:, docs:, test:)
- Messages en anglais, concis et descriptifs

## Autonomie
- Exécuter les tâches sans demander de validation intermédiaire
- Prendre des décisions et les documenter
- Ne poser des questions que si une décision est vraiment bloquante et irréversible

## Git Remotes
- `origin`: https://github.com/kongo09/philips-airpurifier-coap.git (upstream)
- `fork`: https://github.com/foXaCe/philips-airpurifier-coap.git (your fork)
