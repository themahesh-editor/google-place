# Google Place Lead Discovery Experiment

यह repository **सिर्फ verified business leads collect करती है**। इसमें Gmail sending नहीं है।

## Flow

1. Hardcoded seed business niche चुना जाता है।
2. NVIDIA LLM उसी niche के लिए 100 diverse search queries बनाता है।
3. Python सीमित Google Places Text Search requests चलाता है।
4. एक Text Search response में business name, address, website, types और status लिया जाता है।
5. Python duplicate और seen-domain filtering करता है।
6. Python public business website crawl करता है और public emails निकालता है।
7. Syntax, domain match, free/disposable domain और MX checks होते हैं।
8. NVIDIA LLM website evidence के आधार पर conservative LOCAL/REGIONAL qualification करता है।
9. PASS leads `leads_crm.csv` में save होती हैं।
10. पहले देखे गए domains `seen_domains.csv` में रहते हैं और अगले runs में फिर नहीं चुने जाते।
11. `candidate_memory.jsonl` में full Google response dump नहीं रखा जाता; processing state, Place ID और hashed domain memory रखी जाती है।

## Secrets

GitHub Repository Secrets:

- `NVIDIA_API_KEY`
- `GOOGLE_PLACES_API_KEY`

Secrets को code में hardcode मत करना।

## Google Places usage design

यह collector `Text Search (New)` में `websiteUri` मांगता है, इसलिए यह Enterprise Text Search SKU use करता है। India pricing में Enterprise Places SKUs का free monthly threshold 7,000 billable events है। Default run cap 30 Text Search requests है और workflow दिन में एक बार चलता है, इसलिए normal schedule के तहत maximum 900 Text Search request events/month (retries अलग) होंगे।

यह per-minute rate-limit को eliminate नहीं करता। 429 पर backoff और requests के बीच delay रखा गया है।

Google Places policies और applicable storage/caching rules का पालन करना जरूरी है।

## Verified lead definition

A lead is stored only when:

- business has a public website;
- website provides enough public context;
- a public business-domain email is found;
- email syntax is valid;
- email is not free/disposable;
- email domain matches the website domain;
- domain has MX records;
- LLM classifies the business as LOCAL or REGIONAL with confidence >= 0.75;
- the email/domain/company is not already in CRM.

The system can finish below 100 when evidence is insufficient. It does not invent data to hit the target.

## Schedule

The workflow runs daily at `18:17 UTC` (`23:47 IST`) and also supports `workflow_dispatch` for a manual test. GitHub scheduled workflows can be delayed, so the schedule is not an exact-time guarantee.
