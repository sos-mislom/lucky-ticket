# Fiscal check providers

Проверка билетов устроена через провайдеры в `backend/app/fiscal/providers.py`.

`backend/app/jobs/ticket_checks.py` больше не знает деталей конкретного API: он берет список провайдеров, спрашивает у каждого кандидаты для билета, выбирает первого подходящего и сохраняет результат в `parsed_payload.last_official_check`.

## Как добавить новый API

1. Создать клиент API в `backend/app/fiscal/<provider>.py`.
2. Добавить provider-класс в `backend/app/fiscal/providers.py`.
3. Реализовать три метода:

```python
class NewFiscalProvider:
    name = "new-provider"

    def candidates_for(self, ticket: Ticket) -> list[str]:
        return [...]

    def can_check(self, ticket: Ticket, candidates: list[str]) -> bool:
        return ticket.source_format == "new_format" and bool(candidates)

    async def check(self, ticket: Ticket, candidates: list[str]) -> FiscalCheckOutcome:
        result = await self.client.check(...)
        return FiscalCheckOutcome(
        result=result,
        checked_series=candidates[0],
        checked_candidates=candidates,
    )
```

4. Зарегистрировать provider в `build_fiscal_check_providers`.
5. Включить его через переменную:

```env
FISCAL_CHECK_PROVIDERS=ekarta,new-provider
```

## Формат результата

Provider возвращает `FiscalCheckOutcome`, внутри которого лежит общий `FiscalReceiptResult`:

- `provider`: короткое имя API;
- `status`: `verified`, `not_found`, `unknown` или `error`;
- `request_url`: URL запроса или диагностическая строка;
- `receipt_url`: ссылка на официальный чек, если найден;
- `message`: текст ошибки или статуса;
- `raw`: сырой ответ API без секретов.

Если новый API требует другой payload, кладите его в `raw` или расширяйте модель результата аккуратно: старые поля должны остаться, потому что уведомления и история проверок читают `status`, `message` и `receipt_url`.
