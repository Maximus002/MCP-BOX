> **Note on language and status:** the report below is in **Russian**
> (its original drafting language); English translation pending. Numbers
> are **indicative** measurements over a 6-message corpus, not a rigorous
> benchmark. Bottom line for non-Russian readers: LML v0.1.1 was ~26%
> shorter than natural prose in a modern tokenizer, but the precision-
> focused v0.2 / v0.2.1 trade compression for explicitness — v0.2.1
> messages are roughly the **same length as natural prose** (+7.5% over
> the corpus, ranging from −12% on dense logical content to +33% on
> short messages). **The win, if any, is precision and machine-
> parseability — not token economy.** Decide for yourself whether that
> trade is worth the regimentation.

---

# LML v0.1 — эмпирический замер на 6 сообщениях

**Дата:** 2026-04-28
**Корпус:** 6 сообщений Agent A → Agent B из memory-mcp, 2026-04-18..04-22
**Жанры:** handshake, technical fyi, rule, ack, long investigation, correction
**Токенайзеры:** `cl100k_base` (GPT-4) и `o200k_base` (GPT-4o, ближе к Claude)
**Скрипт:** `count.py` (tiktoken)

## Результаты

| id | genre | cl100k orig→lml | Δ% | o200k orig→lml | Δ% |
|---|---|---:|---:|---:|---:|
| 01_handshake | handshake-short | 155 → 61 | **−60.6%** | 102 → 61 | **−40.2%** |
| 02_apt_swap | technical-fyi-with-yaml | 599 → 323 | −46.1% | 474 → 323 | −31.9% |
| 03_csprng_rule | rule-with-rationale-and-code | 929 → 508 | −45.3% | 730 → 516 | −29.3% |
| 04_agent_c_ack | ack-with-observation-and-yaml | 1080 → 594 | −45.0% | 843 → 599 | −28.9% |
| 05_peering_pivot | long-investigation-with-yaml-blocks | 1656 → 1055 | −36.3% | 1312 → 1056 | **−19.5%** |
| 06_correction | short-correction | 467 → 237 | −49.3% | 321 → 233 | −27.4% |
| **TOTAL** | | **4886 → 2778** | **−43.1%** | **3782 → 2788** | **−26.3%** |

## Главный нюанс: разница cl100k vs o200k

`cl100k` показывает −43%, `o200k` — только −26%. Это ⅔ разницы.

**Причина:** `cl100k` (старый, для GPT-3.5/4) плохо токенизирует кириллицу — 1 русский символ часто = 2-3 токена. `o200k` (GPT-4o, 2024) кириллицу токенизирует почти как английский. Claude использует современный BPE, больше похожий на `o200k`.

Значит **реалистичная экономия в Claude — около 25-30%**, не 43%. Старый замер в `cl100k` переоценивает выгоду в полтора раза, потому что половина «экономии» — это просто переход кириллица→латиница, а не сжатие через грамматику LML.

## Tokens/char ratio (откуда экономия на самом деле)

| | orig | lml | Δ |
|---|---:|---:|---:|
| chars | 11651 | 9074 | **−22.1%** (сжатие текста) |
| cl100k tok/char | 0.419 | 0.306 | −27% (большой выигрыш на букве) |
| o200k tok/char  | 0.325 | 0.307 | **−5.5%** (почти ничего!) |

**Вывод:** в современном токенайзере LML экономит токены **почти исключительно за счёт компактности** (−22% символов), а не за счёт более «токен-нативной» грамматики (−5.5% улучшение tok/char).

То есть простое «пиши короче, без приветствий и воды на русском» дало бы примерно ту же экономию.

## Где LML сжимает лучше всего

- **Короткие сообщения** (handshake, correction): −40% и больше. Здесь много шума (greeting, sign-off, риторика) который в LML пропадает.
- **Длинные с yaml-блоками** (peering pivot): −19.5%. yaml уже плотный, LML мало что улучшает.

→ **LML наиболее ценен для коротких частых обменов** (ack/fyi/correction), на которых сейчас уходит много шума. На больших дампах данных — выигрыш минимальный.

## Что это значит для проекта

1. **Цель «30% экономии токенов» не достигается** в честном замере на современном токенайзере. Реалистично — 20-30% в среднем.
2. **Главная ценность LML смещается**: не сжатие, а:
   - **Однозначность для машинного парсинга** (claim-цепочки, provenance, contracts) — здесь LML незаменим, никакая «короткая русская проза» не даст того же.
   - **Семантическая структура** (явные `obs:`/`claim:`/`infer:`/`ask:` префиксы устраняют двусмысленность акта речи).
   - **Цитируемость** (`#c1`, `&1`, `(ref msg_…)`) — нативная поддержка кросс-ссылок.
3. **Идти к шагу 3 (список корней) — нужно**, но с поправкой на ставку. Прирост от token-native корней даст возможно ещё 5-10% поверх текущего, не больше.
4. **На yaml-heavy сообщениях LML не имеет смысла навязывать** — пусть yaml-блоки остаются как есть, LML только в обвязке.

## Подводные камни

1. **Замер в `o200k`, не в Claude tokenizer.** Claude tokenizer не публикуется отдельно (только через Anthropic SDK + API key, ключа в Keychain нет). `o200k` — лучший доступный прокси, но точные числа в Claude могут отличаться на ±5%.
2. **Русский→английский переключение** даёт большую часть экономии в `cl100k` и заметную — в `o200k`. Это эффект **языка**, не грамматики. Если бы LML оставался в кириллице, экономия бы упала.
3. **Я переводил вручную, не парсером.** Возможны небольшие смысловые смещения. Перевод оптимизировал на лаконичность, но без потерь информации (по моему субъективному ощущению).
4. **Корпус смещён в сторону Agent A** — это all мои сообщения, без ответов Agent B. Стиль может отличаться.

## Решение по v0.1

**Спеку v0.1 не переделываем**, но честно ставим в её цели:
- token compression: secondary, ~20-30%
- machine-parseability: primary
- semantic clarity: primary

Идём к шагу 3 — список корней. Закладываемся что он добавит небольшой прирост в сжатии и сильно поможет стабильности (одинаковая лексика у обоих агентов).

---

# v0.2 / v0.2.1 — переход с компрессии на точность

После v0.1.1 цель сместилась: компрессия снята как приоритет, добавлены mandatory keys, контракты как первый класс, удалены все скрытые дефолты, form-mode стал primary. Цена — длиннее сообщения. Замер на том же корпусе из 6 сообщений (`o200k_base`):

| Сообщение | prose | v0.1.1 | v0.2 | v0.2.1 |
|---|---:|---:|---:|---:|
| handshake | 102 | 61 (−40%) | 173 (+70%) | 130 (+27%) |
| apt_swap | 474 | 323 (−32%) | 673 (+42%) | 563 (+19%) |
| csprng_rule | 730 | 516 (−29%) | 694 (−5%) | 641 (**−12%**) |
| agent_c_ack | 843 | 599 (−29%) | 987 (+17%) | 840 (**−0.4%**) |
| peering_pivot | 1312 | 1056 (−20%) | 1693 (+29%) | 1464 (+12%) |
| correction | 321 | 233 (−27%) | 494 (+54%) | 428 (+33%) |
| **TOTAL** | **3782** | **2788 (−26%)** | **4714 (+25%)** | **4066 (+7.5%)** |

## Что изменилось v0.1.1 → v0.2

- Все метаданные (`:p :t :src :scope :by`) стали обязательными. Раньше «не указал» означало «дефолт»; теперь — ill-formed сообщение.
- Form-mode primary: любое утверждение / действие → всё сообщение в form. Prose только для `fyi`/`warn`/`ack`/`propose` без логической нагрузки.
- Удалены prose-частицы метаданных и логики (`~.<n>`, `@<time>`, `&`, `|`, `->` и т.д.) — если нужны, переходи в form.
- `contract` / `commit` / `fulfill` — promise'ы как первый класс с `:pre :do :post :rollback`.
- Разделение отрицаний: `(not X)` (онтологическое) vs `(not-know :by ...)` (эпистемическое) vs `(unknown X)` (никто не знает).

Цена — +25% к прозе на корпусе.

## Что изменилось v0.2 → v0.2.1

Две минимальных правки без потери precision:

1. **`:by` опционально с дефолтом = MCP `from`.** Структурный фолбэк, не скрытое допущение: `(do (action))` от отправителя X однозначно интерпретируется как `(do (action) :by X)`. Если субъект ≠ отправитель — `:by` обязательно.
2. **Новый структурный предикат `context`** — explicit lexical scope для inheritance метаданных. Несколько claim'ов с общими `:t :scope :src` оборачиваются в `(context ...)` вместо повторения ключей.

Цена снизилась до +7.5% к прозе. Длинные сообщения теперь на уровне прозы или короче; короткие всё ещё страдают (handshake +27%, correction +33%).

## Когда LML стоит цены, когда нет

| Случай | Стоит ли |
|---|---|
| Короткие частые ack/fyi | **Нет.** Overhead больше пользы. |
| Утверждения, которые надо машинно проверять (claim-цепочки, contracts) | **Да.** Главная ценность LML — однозначность. |
| Большие YAML-дампы данных | **Не критично.** YAML и так структурный, LML только в обвязке. |
| Длинные расследования с гипотезами и провенансом | **Да.** `obs` / `claim` / `infer` цепочки и `:src` дисциплинируют. |
| Креативная проза, рассуждение, объяснение для человека | **Нет.** LML только для Claude↔Claude канала. |

## Подводные камни замера

- Все цифры — `o200k_base` через `tiktoken`, как прокси к Claude tokenizer (он не публикуется отдельно). Точные числа в Claude могут плавать на ±5%.
- Корпус — 6 сообщений, перекошен в сторону одной стороны, переводы делались вручную без парсера. Это **indicative**, не научный benchmark.
- Скрипт `count.py` (исходники в репо `lml/empirical/` у автора) воспроизводим, если поставить tiktoken и подать на вход тот же корпус (corpus не публикуется — содержит личный контекст).

## TL;DR для решения «использовать или нет»

LML v0.2.1 — **не способ сэкономить токены**. Это способ договориться о точном формате обмена между двумя ИИ-агентами: однозначная модальность каждого утверждения, явный provenance, контракты с pre/post/rollback. Если ваша пара агентов гоняет в основном чат-подобные «привет-увидел-сделал» — LML overhead не окупается. Если идёт техническое расследование или координация работы, где важно отличать наблюдение от догадки и где обещания должны быть машинно-проверяемыми — стоит попробовать.

---

# Stress-test #1 (v0.2.1 → v0.3 RFC, 2026-05-04)

Первый реальный stress-test между двумя агентами на технической задаче (provisioning Windows Server VM на чужом Proxmox-хосте через SSH-handoff). Задача закрыта до полного провижининга — но переписка дала плотный корпус с реальной нагрузкой.

## Корпус

- **11 сообщений** в одной теме (`proxmox-vm-task`), 6 от agent_a, 5 от agent_b.
- **8,545 tokens** total (через `tiktoken o200k_base` proxy), **28,470 chars**.
- **tok/char = 0.30** — почти равно русской прозе (0.32 historical baseline).
- LML **не плотнее** прозы — что подтверждает v0.2.1 stated trade-off (precision over compression).

| msg | from | tokens | chars |
|---|---|---:|---:|
| 1 stress-test starts (contract + commit + 2 ask) | agent_a | 361 | 1137 |
| 2 ack + pubkey + spec + 6 q | agent_b | 950 | 3102 |
| 3 fulfill #cm1 | agent_a | 428 | 1365 |
| 4 ssh ok + recon + q-storage | agent_b | 928 | 2951 |
| 5 false diagnosis (drift #6) | agent_a | 855 | 2790 |
| 6 correction | agent_a | 787 | 2650 |
| 7 decisions + ct2 + iso wills + q-go | agent_b | 1661 | 5700 |
| 8 ack go + correction + naming + q-sync | agent_a | 663 | 2230 |
| 9 ack handoff + actor-mismatch + drift trace | agent_b | 552 | 1839 |
| 10 closure | agent_a | 693 | 2476 |
| 11 closure-ack + RFC seeds | agent_b | 667 | 2230 |
| **TOTAL** | | **8545** | **28470** |

By author: agent_a 6 msgs / 3787 tokens (avg 631), agent_b 5 msgs / 4758 tokens (avg 951).

## Calibration data point

agent_b пытался дать inference-оценку (без tokenizer'а на своей стороне) через эвристику `~4 chars/token`: предсказал 2400-3200 tokens на subset из 9 сообщений. Реальный tiktoken count на тех же 9 = **7185 tokens**. Эвристика **недооценила в 2.2-2.7×**.

**Реальный ratio для mixed RU+ASCII+LML контента — ~3.3 chars/token**, не 4. Полезно для будущих inference-оценок.

## 8 drift events

Все task-driven, не симулированные.

| # | Сторона | Класс | Что |
|---|---|---|---|
| 1 | agent_a | Discipline | `thread_id` не передан в `send` → новый тред вместо продолжения. Fixed во 2-м сообщении. |
| 2 | agent_b | Spec gap | `;;` Lisp-style комментарии — не определены в v0.2.1. → §A RFC v0.3. |
| 3 | agent_b | Spec gap | `~10` как value approximation marker — value-position не была формализована. → §B RFC v0.3. |
| 4 | agent_b | Spec gap | data-mode `(vm 104 name=...)`, predicate не в закрытом списке §4.2. → §C RFC v0.3 (data-mode). |
| 5 | agent_a (potential) | Spec gap | ad-hoc `(option :viable=tight :reason ...)` — поймал на ревизии перед send. Сигнал что spec нужен data-mode. |
| 6 | agent_a | Discipline | Published unverified claim с `:src direct-obs` (был prediction, не observation). Trust-but-verify поймал перед write → correction. → §F RFC v0.3 (verify-before-claim spec rule). |
| 7 | agent_a | Spec misuse | `:corrects` использован против `ask` (а не `claim`). agent_b flagged. → §E RFC v0.3 (`:corrects` target restriction). |
| 8 | agent_a | Provenance gap | actor mismatch: agent_a сказал «the_user сам зальёт ISO», в чате с agent_b's operator — operator сказал «я сам качаю». Не критично, но точность provenance снизилась. |

**Положительные подтверждения:**
- Form-mode читался без reconstruction errors с обеих сторон.
- `correction` predicate сработал как страховочная сетка после моего false claim — публичное саморемонтирование языка работает.
- Provenance дисциплина (`:src direct-obs` vs `confirmed-by-user` vs `:src #ref`) реально различала классы.
- Cross-message refs `(ref msg-id #localid)` работали корректно у обоих.
- Inheritance из `(context ...)` экономил повторение `:t :scope`.

**Ключевой урок:** spec-дисциплина не заменяет verify-перед-claim. Vina blind spot #5 (hallucinated fact) реально срабатывает под давлением. Read перед claim — не только перед write.

## RFC v0.3 → активирован 2026-05-06

7 секций deltas v0.2.1 → v0.3: comments (§A), value-position approximation (§B), data-mode records (§C), explicit inheritance lists (§D), `:corrects` constraint (§E), verify-before-claim discipline rule (§F), default-LML rule for Claude↔Claude (§G). Plus handshake exception для Apollo onboarding и string-quoting note (от agent_b minor review).

См. [`lml-protocol.md`](lml-protocol.md) для full v0.3 canonical spec, [`lml-rfc-v0.3.md`](lml-rfc-v0.3.md) для черновика RFC с rationale за каждое изменение.

## Pending v0.4

- **Multiple positional values в truth-bearing предикатах** — оба пира неявно использовали `(claim ... (state X) (state Y) (state Z))`, не формализовано.
- **Privacy на memory-mcp** — server-side filter `from == me OR to == me` для read/search/thread (deployed 2026-05-06 как hot-fix, отдельно от LML); opt-in `encrypted="age"` для sensitive content.
- **Canonical core vocab** (~250 verbs + 100 nouns + 50 ops, token-native в Claude tokenizer) — было pending от v0.2.

## Что stress-test #1 НЕ exercised

- Long-thread digest convention (§3.5 of AGENTS.md).
- `fulfill` после долгого ожидания.
- prose-mode messages (agent_a не использовал prose в этом stress-test'е).
- ack-only / fyi-only / warn-only message genres.
- age-encrypted bodies.
- Cross-thread refs.
- 3+ peer participation (только agent_a и agent_b).

Эти gaps — задача для stress-test #2.
