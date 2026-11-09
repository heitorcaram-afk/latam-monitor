# Monitor de preços LATAM — UDI → AMS

Rastreia passagens **LATAM** de **Uberlândia (UDI) para Amsterdã (AMS)**:
- Ida: **21/01/2027**
- Volta: **30/01/2027** e **31/01/2027** (as duas são consultadas)

Salva o histórico em `prices.db` (SQLite) e avisa por Telegram/e-mail quando:
- o preço cai em relação à última checagem;
- bate um novo menor preço histórico;
- fica abaixo do `TARGET_PRICE`.

## Fonte de dados
Usa a **SerpApi (Google Flights)**. A API self-service da Amadeus foi desativada em 17/07/2026,
e raspar o site da LATAM diretamente viola os termos de uso e quebra com facilidade.
O filtro `include_airlines=LA` + checagem local garantem só ofertas com LATAM.

## Uso
```bash
cd latam-monitor
pip install -r requirements.txt
export SERPAPI_KEY=sua_chave
export TARGET_PRICE=6500        # opcional
python monitor.py
```

Agendar (cron, a cada 6h):
```
0 */6 * * * cd /caminho/latam-monitor && SERPAPI_KEY=xxx python monitor.py >> monitor.log 2>&1
```

Ou use o workflow `.github/workflows/monitor.yml` (secrets: `SERPAPI_KEY`, e opcionalmente
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; variável: `TARGET_PRICE`).

## Consumo da cota
2 buscas por execução → a cada 6h = ~240 buscas/mês (cabe no plano gratuito de ~250).
Para mais frequência, ajuste o cron ou assine um plano pago.

## Ver histórico
```bash
sqlite3 prices.db "SELECT checked_at, inbound, price, stops FROM prices ORDER BY id DESC LIMIT 20;"
```

## Observações
- O preço é por passageiro, ida e volta, em BRL.
- UDI→AMS exige conexão (normalmente via GRU); o campo `stops` mostra isso.
- Se quiser, dá para adicionar GRU/CNF/BSB como aeroportos alternativos de saída.
