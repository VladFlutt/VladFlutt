# Проверка skills в CI

Workflow `.github/workflows/scan-skills.yml` запускает [Cisco skill-scanner](https://pypi.org/project/cisco-ai-skill-scanner/)
(статический и поведенческий анализ, без LLM и без API-ключей) на каждый push и pull request,
который меняет `.claude/skills/**` или саму проверку.

- Отчёт выводится в summary запуска; полный `report.md` / `report.json` — в артефакте `skill-scan-report`.
- Запуск падает **только** на новых замечаниях уровня `CRITICAL`, которых нет в `baseline.json`.
  HIGH и ниже показываются в отчёте, но не блокируют.
- После push в `main` последний отчёт кладётся в ветку `skill-scan-report`.

## Если проверка упала

1. Откройте summary запуска — там таблица «Новые замечания» с файлом, строкой и советом по исправлению.
2. Исправьте skill или, если это ложное срабатывание, примите замечание:
   скачайте `report.json` из артефакта и выполните
   `python3 .github/skill-scan/gate.py report.json --update-baseline`,
   затем впишите в поле `reason` у новых записей, почему это безопасно.
   Для точечной переоценки конкретного правила в конкретном skill есть
   `.github/skill-scanner-policy.yaml` (с причиной и сроком действия, подробности в `SECURITY-NOTES.md`).

Порог можно поменять через `FAIL_ON` в workflow (`CRITICAL`, `HIGH`, ...).
