# Fiscal Integrations

## Compatibility Strategy

Ticket formats differ by city, so the app should treat compatibility as two layers:

1. Universal fiscal receipt data: any ticket, OFD link, or QR text containing `t`, `s`, `fn`, `i`, `fp`, `n`.
2. City/provider adapters: official lookup pages for transport operators that have their own ticket series and number search.

The first layer is now supported as `fns_fiscal_qr_v1`. It extracts:

- trip/receipt time from `t`;
- price from `s`;
- fiscal drive number from `fn`;
- fiscal document number from `i`;
- fiscal sign from `fp`;
- operation type from `n`.

When a city ticket only has a generic fiscal QR/OFD URL, the fiscal document number is used as the scoreable number. When a city ticket also prints a transport ticket number, city adapters should prefer the transport ticket number for happiness scoring and keep fiscal fields for verification.

## EKARTA / Екатеринбург

The public instruction page is:

- `http://www.ekarta-ek.ru/fc`
- canonical content path: `/informatsiya/fchek/`

It links to the fiscal receipt app:

- `http://f.ekarta-ek.ru/fiscal/`

The official page states that a fiscal receipt is available on the next day after the trip, after terminal data is transferred to the server at the end of the working shift.

The Angular app displays a masked series (`000000-00000000-000`), but sends the
unmasked 17-digit value to the API:

```text
GET http://f.ekarta-ek.ru/fiscal/api/v1/cheque/{17_digit_series}{ticket_number}
GET http://f.ekarta-ek.ru/fiscal/api/v1/cheque/qr/QR{qr_series}%20{qr_number}
```

For the provided ticket, the likely lookup was:

```text
GET http://f.ekarta-ek.ru/fiscal/api/v1/cheque/260428000000010520369
```

At the time of probing it returned a receipt URL:

```json
{"error":null,"format":"URL","data":{"url":"https://consumer.1-ofd.ru/ticket?t=20260428T1746&s=42.00&fn=0000000000000000&i=00001&fp=0000000000&n=1"}}
```

This should be treated as `pending_check` during the first day and retried before becoming `rejected`.

For QR PDF tickets, EKARTA uses a separate lookup:

```text
GET http://f.ekarta-ek.ru/fiscal/api/v1/cheque/qr/QR{12_digit_series}%20{17_digit_number}
```

The provided QR ticket was parsed as:

```text
series: QR000000000040
number: 20000101000000098
lookup: http://f.ekarta-ek.ru/fiscal/api/v1/cheque/qr/QR000000000040%2020000101000000098
```

At the time of probing it also returned `Билет не найден`.

## Electronic Bank Card Tickets

For MVP, electronic tickets should be imported from official passenger cabinets or user-provided receipts. The product should avoid scraping private bank accounts and should not ask for bank card credentials.

## Provider Matrix

| City / provider | Official public source | Current support | Notes |
| --- | --- | --- | --- |
| Екатеринбург / EKARTA | `http://www.ekarta-ek.ru/fc`, `http://f.ekarta-ek.ru/fiscal/` | Parser + lookup client | Supports thermal tickets and QR PDF tickets. |
| Any Russian city with fiscal QR/OFD URL | QR or URL with `t`, `s`, `fn`, `i`, `fp`, `n` | Parser support | Verification can later go through official FNS/OFD integrations where allowed. |
| Челябинск / МУП СОД | `https://bilet174.ru/` | Planned adapter | Public form uses `seria`, `bilet`, `bdata`; receipt data appears after 24 hours. |
| Нижний Новгород / Ситикард | `https://siticard.ru/services/ofd/` | Planned adapter | Public service for cash receipt retrieval after travel payment. |

Potential future providers:

- local transport card passenger cabinets;
- NSPK passenger ticket/receipt pages where officially available;
- operator partner APIs, if a transport operator grants access.
