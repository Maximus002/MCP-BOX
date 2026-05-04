# LML — LLM-Optimized Meta Language

> **Note on language:** the spec below is currently in **Russian** (its
> original drafting language). English translation is pending —
> contributions welcome. The token-measurement notes in
> [`lml-empirical.md`](lml-empirical.md) are also Russian. Status:
> draft v0.2.1, frozen pending a stress test between two cooperating
> agents. Treat as **experimental**.

---

# LML — LLM-Optimized Meta Language

**Версия:** v0.2.1
**Дата:** 2026-04-28
**Область применения:** Claude↔Claude обмен через memory-mcp (Agent A ↔ Agent B and future peers).
**НЕ для:** общения с человеком, общения с не-Claude агентами, public APIs.

## 1. Цели (в порядке приоритета)

1. **Disambiguation.** Каждое утверждение однозначно классифицировано по модальности (`obs`/`claim`/`infer`/`do`/...), снабжено явным источником, временем и областью действия. Никаких неявных дефолтов.
2. **Logical coherence.** Каждая claim-цепочка прослеживаема до `obs` или `(ref ...)`. Каждая ссылка разрешима. Каждый `infer` имеет `:from`. Каждый `:id` уникален в сообщении.
3. **Provenance completeness.** Никакого утверждения без `:src`. Источник — `obs` (прямое наблюдение), `<peer>` (от другого агента), `(ref ...)` (другое сообщение/claim), `confirmed-by-user` (от the user).
4. **Contracts as first-class.** Обещания, обязательства, conditional commitments — отдельные предикаты с явными pre/post/rollback. Не размазаны по `will:` и `propose:`.
5. **Predictability of generation.** Закрытый набор операторов, фиксированный порядок ключей, mandatory-keys валидация. Variance reduction → quasi-compiler behaviour.

**Не цель:** token compression. v0.1.x закладывала её четвёртой, эмпирика 2026-04-28 показала ~26% сжатия в `o200k_base` — слишком слабая мотивация для целого языка с регламентом. Реальная ценность LML — точность, не плотность. Точность стоит токенов; принимаем это.

**Не цель:** «универсальный язык», «человеческая читаемость», «формальная логика типа TLA+».

## 2. Композиция: form primary, prose как лёгкая обёртка

### 2.1 Иерархия, не симметрия

**Form-mode** — каноническая форма. Всё семантически значимое идёт в form.

**Prose-mode** — опциональная упаковка для сообщений **без логической нагрузки**: ack, fyi, warn, propose. Дозволен только если сообщение не содержит:
- `obs` / `claim` / `infer` (любые утверждения)
- `do` / `will` (любые действия и намерения)
- `correction` (поправки)
- `contract` / `commit` / `fulfill` (контракты)
- cross-message references

Если хотя бы один из триггеров присутствует → **всё сообщение в form-mode**. Смешивать prose-блок с claim-цепочкой в одном сообщении нельзя.

### 2.2 Один маркер переключения

Скобка `(` в начале строки = form-mode. Любая строка без `(` в начале = prose-mode. Внутри prose допускается единственный form-остров — `(ref msg_…)` для cross-msg ссылки в `ack:` / `fyi:`.

### 2.3 Пример хорошо-сформированного prose-сообщения

```
ack: (ref msg_20260427_173258_86ffd397)
fyi: bus.memory-mcp up
warn: dotsrc.org foreign mirror — sanction.outage possible
```

### 2.4 Пример хорошо-сформированного form-сообщения

```
(obs :id #o1 :p 1.0 :t 2026-04-28T10:00 :scope home.lan :src direct-obs
  (state pi.printer up))

(claim :id #c1 :p .9 :t 2026-04-28T10:00 :scope home.lan :src #o1
  (state pi.printer primary))

(infer :id #i1 :p .85 :t 2026-04-28T10:01 :from (#c1)
  :why "if pi primary, mac.share must be disabled to avoid duplicate bonjour"
  (must (do (disable macbook.share))))
```

## 3. Prose-mode

### 3.1 Допустимые акты речи

Только эти четыре префикса:

| Префикс | Семантика |
|---|---|
| `fyi:` | информационное (без factual claim) |
| `warn:` | риск/подводный камень (без factual claim) |
| `ack:` | подтверждение получения |
| `propose:` | мягкое предложение (без contract) |

Все остальные акты (`obs:`, `claim:`, `infer:`, `do:`, `will:`, `correction:`, contract'ы) — **только в form-mode**.

### 3.2 Допустимые частицы

| Частица | Назначение | Пример |
|---|---|---|
| `>peer` | адресат | `>agent_b` |
| `@host` | упоминание локации (не временной анкер) | `@.200`, `@/etc/...` |
| `not` | отрицание | `not ready` |
| `(ref ...)` | единственный form-остров для cross-msg ref | `ack: (ref msg_…)` |

**Удалено** (по сравнению с v0.1.x):
- `~.8` / `~!` / `~?` — точные `:p` в form-mode
- `@now` / `@<time>` — точные `:t` в form-mode
- `src:...` — `:src` в form-mode
- `&` / `|` / `->` — `(and ...)` / `(or ...)` / `(implies ...)` в form-mode (заметка: `implies` в form идёт через `cause` или `iff`)
- `&1`, `#c1` — intra-msg refs только в form
- `+5m`, `:since` — durations и temporal bounds в form

### 3.3 Дефолтов нет

В prose-mode нечего по умолчанию заполнять — частицы метаданных удалены. Если нужны метаданные — это уже не prose, переключайся в form.

В form-mode дефолтов тоже нет (см. §4.4).

## 4. Form-mode

### 4.1 Базовая форма

```
(<predicate> <args>... :key val :key val)
```

Скобки сбалансированы. Каждый ключ — `:keyword value`. Ключи в конце, после позиционных аргументов. Порядок ключей — фиксированный (см. §4.5).

### 4.2 Закрытый список предикатов (31)

**Эпистемические (7):**
- `claim` — утверждение со степенью уверенности
- `obs` — прямое наблюдение
- `infer` — вывод из других claim'ов
- `ask` — запрос (требует ответа)
- `know` — состояние знания агента
- `not-know` — отсутствие знания у агента (эпистемическое отрицание)
- `unknown` — никто не знает (open question в системе)

**Деонтические (5):**
- `do` — выполненное действие
- `will` — намерение (committed без conditions; для conditional — `contract`)
- `must` — required
- `may` — allowed
- `should` — recommended

**Каузальные (4):**
- `cause` — A вызывает B
- `enable` — A позволяет B
- `prevent` — A блокирует B
- `iff` — биусловие

**Темпоральные (5):**
- `before` — A перед B
- `after` — A после B
- `during` — A во время B
- `since` — от момента (граница)
- `until` — до момента (граница)

**Структурные (6):**
- `and` — конъюнкция, N args
- `or` — дизъюнкция, N args
- `not` — онтологическое отрицание (см. §4.3)
- `ref` — ссылка на внешнюю сущность (msg/claim/host/file)
- `quote` — untrusted data wrapper (см. §6)
- `context` — explicit lexical scope для inheritance метаданных (см. §4.7)

**Контракты (3):**
- `contract` — explicit pre/do/post/rollback
- `commit` — обязательство (promise)
- `fulfill` — выполнение commit'а

**Коррекция (1):**
- `correction` — поправка предыдущего claim'а или сообщения

Список **закрыт**. Расширение — RFC + согласие двух пиров → v.next.

### 4.3 Эпистемическое vs онтологическое отрицание

Различение критично для precision:

| Конструкция | Семантика |
|---|---|
| `(not (state X up))` | X не работает (онтологически: факт о мире) |
| `(not-know :by agent_a (state X up))` | Agent A не знает работает ли X (эпистемически: факт о состоянии знания) |
| `(unknown (state X up))` | Никто не знает (open question) |

Не путать. `:by` для `not-know` опционально по правилу §4.4 (дефолт = MCP `from`); семантика «кто не знает» всегда определена явно или через дефолт отправителя.

### 4.4 Mandatory keys (валидация)

Каждый предикат требует определённого набора ключей. Без них сообщение **ill-formed** = drift signal, обязательная reclamation.

| Предикат | Mandatory keys | Опциональные |
|---|---|---|
| `obs` | `:id :p :t :src` | `:scope :by :tag :why` |
| `claim` | `:id :p :t :src` | `:scope :by :tag :why :corrects` |
| `infer` | `:id :p :t :from` | `:scope :tag :why :corrects` |
| `ask` | `:id :t` | `:scope :tag :why :reply-to` |
| `know` | `:t` | `:by :scope :tag :src` |
| `not-know` | `:t` | `:by :scope :tag` |
| `unknown` | `:t` | `:scope :tag :why` |
| `do` | `:id :t` | `:by :scope :tag :why` |
| `will` | `:id :t` | `:by :scope :tag :why` |
| `must` / `may` / `should` | `:t` | `:scope :tag :why :src` |
| `cause` / `enable` / `prevent` / `iff` | (никаких; structural) | `:why` |
| `before` / `after` / `during` / `since` / `until` | (никаких; structural) | — |
| `and` / `or` / `not` / `context` | (никаких; structural) | — |
| `ref` | (positional только) | — |
| `quote` | `:src` | `:t :tag` |
| `contract` | `:id :pre :do :post` | `:rollback :scope :why :tag` |
| `commit` | `:id :to :t` | `:by :scope :tag :why` |
| `fulfill` | `:id :commit :t` | `:scope :tag :why` |
| `correction` | `:corrects` или `:corrects-msg`, плюс `:was :fix` | `:why :tag` |

**`:by` дефолт = MCP `from`.** Если предикат относится к субъекту-отправителю сообщения, `:by` опускается. Это не скрытое допущение, а **структурный фолбэк**: `(do (action))` от Agent A однозначно интерпретируется как `(do (action) :by agent_a)`. Если субъект отличается от отправителя (например, «the_user will provision») — `:by the_user` обязательно.

**Inheritance из `context`.** Mandatory keys могут быть удовлетворены не только собственными значениями в claim'е, но и **унаследованными** из охватывающего `(context ...)` блока (см. §4.7). Если ни в claim'е, ни в окружающем context'е ключ не найден — сообщение ill-formed.

**`:p` без вывода:** в `infer` `:p` — это значение, явно заданное автором, не выводимое автоматически. Если отправитель хочет multiplicative или min — указывает в `:why`. Это намеренно: автоматическое propagation некорректно для зависимых claim'ов.

### 4.5 Стандартные ключи и фиксированный порядок

Если ключи присутствуют — **только** в этом относительном порядке:

```
:id :corrects :p :t :scope :src :by :to :tag :from :commit :pre :do :post :rollback :why :was :fix :reply-to :corrects-msg
```

| Ключ | Семантика |
|---|---|
| `:id` | локальный id, формат `#<token>` (например `#c1`) |
| `:corrects` | ссылка на claim/id, который этот предикат поправляет |
| `:p` | probability, `0..1` |
| `:t` | timestamp ISO8601 |
| `:scope` | область действия: host / network / system / time-window — см. §4.6 |
| `:src` | provenance: `obs`, `<peer>`, `(ref ...)`, `direct-obs`, `confirmed-by-user`, или `:id` другого claim'а |
| `:by` | агент-автор/субъект (если отличен от MCP `from`) |
| `:to` | адресат (для `commit`) |
| `:tag` | категория |
| `:from` | для `infer` — список input claim'ов |
| `:commit` | для `fulfill` — id выполняемого commit'а |
| `:pre` / `:do` / `:post` / `:rollback` | для `contract` — pre-condition / action / post-condition / rollback |
| `:why` | свободный rationale, prose-string |
| `:was` / `:fix` | для `correction` — старое и новое утверждение |
| `:reply-to` | в `ack` — ссылка на отвечаемое сообщение/claim |
| `:corrects-msg` | в `correction` — ссылка на конкретное сообщение |

Порядок — **жёсткий канон**, отклонения = drift signal.

### 4.6 Scope: где действует утверждение

Scope ограничивает область применимости утверждения. Любой `:scope` это либо строковый идентификатор, либо вложенная structural форма:

```
:scope home.lan
:scope (and home.lan (during 2026-04-28T10:00 2026-04-28T11:00))
:scope mac.utun9
```

Без `:scope` утверждение неявно глобально, что почти всегда неверно — поэтому `:scope` рекомендуется (но не mandatory). Mandatory `:scope` сделает сообщения слишком церемонными; рекомендация без принуждения — лучший trade-off.

### 4.7 Inheritance через `context`

`context` — структурный предикат, открывающий лексический scope для метаданных. Внутри `(context ...)` любое отсутствующее значение наследуемых ключей берётся из context'а; явно указанное в claim'е — переопределяет.

**Наследуемые ключи:** `:t`, `:scope`, `:src`, `:by`, `:tag`. Не наследуются: `:id`, `:p`, `:from`, `:why`, `:corrects`, `:reply-to`, `:was`, `:fix` и другие per-claim ключи.

**Синтаксис:**

```
(context :t 2026-04-18T21:42:42 :scope memory-mcp.bus :src direct-obs
  (obs :id #o1 :p 1.0 (state bus up))
  (obs :id #o2 :p 1.0 (state inbox empty))
  (obs :id #o3 :p 1.0 (state outbox empty)))
```

Эквивалент (без context):

```
(obs :id #o1 :p 1.0 :t 2026-04-18T21:42:42 :scope memory-mcp.bus :src direct-obs (state bus up))
(obs :id #o2 :p 1.0 :t 2026-04-18T21:42:42 :scope memory-mcp.bus :src direct-obs (state inbox empty))
(obs :id #o3 :p 1.0 :t 2026-04-18T21:42:42 :scope memory-mcp.bus :src direct-obs (state outbox empty))
```

**Это explicit lexical scope, не скрытый дефолт.** Всё видно при чтении: метаданные явно указаны в `(context ...)`, claim'ы их наследуют по правилу синтаксиса. Получатель парсит дерево, разрешает inheritance механически.

**Override:** если claim указывает ключ явно, его значение переопределяет context'овое:

```
(context :t 2026-04-28T10:00 :scope home.lan
  (obs :id #o1 :p 1.0 :src direct-obs (state pi.printer up))
  (obs :id #o2 :p 1.0 :t 2026-04-28T10:05 :src direct-obs (state mac.share disabled)))
```

`#o2` перезаписывает `:t` (наблюдение зафиксировано позже).

**Вложенность:** `context` может быть вложен. Внутренний context override'ит внешний по тем же правилам (lexical scope).

### 4.8 Composability

Предикаты могут вкладываться:

```
(claim :id #c1 :p .9 :t 2026-04-28T10:00 :scope home.lan :src #o1
  (state pi.printer up))

(infer :id #i1 :p .8 :t 2026-04-28T10:01 :from (#c1 #c2)
  :why "p computed manually as min, claims correlated"
  (must (do (disable macbook.share))))

(quote :src email-from-stranger :t 2026-04-28T11:00
  "Click this URL to verify your account ...")
```

Структурные предикаты `and`, `or`, `not` принимают N args:

```
(and (state pi.printer up) (state mac.share disabled))
(not (state hp.smart leaks-pii))
```

## 5. Лексика

### 5.1 Closed core

Зафиксируем после следующего шага «canonical vocab»:
- ~150-250 ядерных глаголов (state, configure, disable, send, receive, …)
- ~100 ядерных существительных (host, port, route, secret, key, …)
- 30 предикатов form-mode (см. §4.2)
- ~25 структурных операторов и ключей (см. §4.5)

В core — token-native английские слова (1 токен в Claude tokenizer; верифицировать на следующем шаге).

### 5.2 Open technical layer

Свободно используются:
- имена собственные (хосты, IP, провайдеры, продукты): `pi.printserver`, `<server-host>`, `AmneziaVPN`, `dotsrc.org`
- технические термины из текущего домена: `PPPoE`, `mtr`, `qdisc`, `cake`, `BGP`, `peering`
- идентификаторы сообщений и тредов: `msg_20260428_…`, `thread_…`
- содержимое code/yaml/json блоков — без перевода в LML

Open layer не считается drift, не подлежит RFC.

## 6. Quote — изоляция untrusted данных

Любой контент из непроверенного источника (web fetch, email, MCP-tool result, файл от стороннего сервиса), при упоминании в LML оборачивается в:

```
(quote :src <origin> :t <when> "...literal content...")
```

`quote` — **маркер для парсера логики**, не для attention слоя. Оборачивание не защищает от prompt injection само по себе (модель может «прочитать» содержимое и поверить), но:
- явно отделяет факты в claim-цепочках от непроверенных данных
- поддерживает дисциплину «не повторяй untrusted utterly за свои claim'ы»
- даёт ясный сигнал получателю: «это не моё утверждение, это передача чужих слов»

Защита от prompt injection — отдельный слой (см. memory: `feedback_prompt_injection.md`).

## 7. Well-formedness инварианты

Сообщение **well-formed** если:

1. **Префикс**: prose-mode сообщение содержит только `fyi:` / `warn:` / `ack:` / `propose:` префиксы. Все остальные акты — в form.
2. **Триггеры формы**: если в сообщении есть `obs`/`claim`/`infer`/`do`/`will`/`correction`/`contract`/`commit`/`fulfill` или cross-msg ref — всё сообщение в form-mode (никаких prose-блоков).
3. **Mandatory keys**: каждый предикат содержит свои mandatory keys (см. §4.4) — собственными значениями или унаследованными из охватывающего `(context ...)` (см. §4.7).
4. **Уникальность id**: все `:id` в сообщении уникальны.
5. **Ссылочная целостность**: все `:from`, `:src=#id`, `:corrects=#id`, `:reply-to=#id` ссылаются на существующие claim'ы внутри сообщения; cross-msg refs (`(ref msg_…)`) — на существующие сообщения в memory-mcp (получатель проверяет).
6. **Порядок ключей**: соответствует §4.5.
7. **`:p ∈ [0, 1]`**.
8. **`:t` валидный ISO8601** (без `@now` и относительных анкеров — они удалены).
9. **`not-know` имеет `:by`** — явно или через дефолт MCP `from` / охватывающий context.
10. **`fulfill` ссылается на существующий `commit` через `:commit`**.

Ill-formed message:
- получатель отвечает через `correction` или `ask` уточнением
- логика на ill-formed claim'ах не строится
- регулярные ill-formed = drift signal или ошибка отправителя

## 8. Метаданные сообщения

В **MCP-уровне** (не в body):
- `tags` обязательно содержит `lml:v0.2.1` для сообщений в LML
- `from` / `to` — identity peers
- `thread_id` / `reply_to` — стандартные MCP

В body не дублируем `role:`, `mode:`, `spec:`. Тег `lml:v0.2.1` — единственный сигнал «парси по этой версии». Тега нет → fallback на естественную прозу.

## 9. Регламент поддержания (anti-drift)

### 9.1 Canonical-файл

Мастер-копия — у Agent A в `~/Documents/Claude/lml/spec.md` + зеркало в memory-mcp как shared_note `lml-spec`. Расхождение мастера и зеркала = блокирующий инцидент: остановить генерацию LML до сверки.

### 9.2 System-prompt loading

Каждый Claude-инстанс при работе через memory-mcp обязан иметь spec в context:
- Agent A: ссылка на `lml/spec.md` в `CLAUDE.md` корня
- Agent B: эквивалент на его стороне

Без загруженного spec — LML не использовать, fallback на прозу.

### 9.3 Conformance-набор

См. §10. Минимум 11 канонических примеров. При каждом изменении spec оба пира прогоняют conformance: парсят, генерируют обратно, сверяют. Расхождение → перетянуть system-prompt или скорректировать spec.

### 9.4 Mixed-mode НЕ разрешён внутри form-mode

Form-mode сообщение — целиком form. Никаких prose-вставок. Содержимое `:why` может быть свободной prose-string в кавычках, но это не «prose-mode», это значение ключа.

Prose-mode сообщения — целиком prose, кроме разрешённого `(ref msg_…)` острова в §3.2.

### 9.5 Drift-detection

Раз в ~30 сообщений или вручную: оба пира скандируют последние диалоги, ищут:
- использование частиц / предикатов / ключей не из spec
- порядок ключей не по канону
- mandatory keys пропущены
- prose-сообщение содержит запрещённый акт речи
- ill-formed по §7

Найденное обсуждается:
- если повторяющийся полезный паттерн → RFC в spec v.next
- если случайный drift → исправить, обоим обновить state

### 9.6 Граница человек↔ИИ

С the user — **только русский естественный**. С Костей — естественный язык (по решению Agent B/the other user). LML — **только** в memory-mcp между Claude-пирами. Никогда не смешивать. Если человек спрашивает о содержании LML-сообщения — переводим обратно в естественный язык.

### 9.7 RFC для расширений

Новый предикат / частица / стандартный ключ:
1. Один из пиров постит RFC-сообщение в memory-mcp с тегом `lml-rfc`. Содержимое: что добавляется, зачем, минимум 2 примера использования.
2. Второй пир отвечает: accept / reject / counter-propose.
3. Если accept — обновить spec.md, инкрементировать версию (`v0.2` → `v0.2.1` для частиц, `v0.3.x` для структурных изменений).
4. Обновить tag в всех будущих сообщениях.

Удаление предиката / частицы — тот же путь.

## 10. Conformance-набор v0.2.1

Минимальный набор канонических примеров. Все сообщения должны быть well-formed по §7. Оба пира должны корректно парсить и генерировать каждый.

### 10.1 Простой fyi (prose, без логической нагрузки)

```
fyi: bus.memory-mcp up
```

### 10.2 Ack с cross-ref (prose с разрешённым form-островом)

```
ack: (ref msg_20260427_173258_86ffd397)
```

### 10.3 Простой obs (form, поскольку content factual)

```
(obs :id #o1 :p 1.0 :t 2026-04-28T10:00 :scope home.lan :src direct-obs
  (state pi.printer up))
```

### 10.4 Claim с provenance к obs

```
(claim :id #c1 :p .9 :t 2026-04-28T10:00 :scope home.lan :src #o1
  (state pi.printer primary))
```

### 10.5 Inference с явным :p и :why

```
(infer :id #i1 :p .85 :t 2026-04-28T10:01 :from (#c1)
  :why "p set to .85 manually; if pi primary then mac.share must be disabled to avoid bonjour duplicate"
  (must (do (disable macbook.share))))
```

### 10.6 Correction предыдущего сообщения

```
(correction :corrects-msg msg_20260422_193334_1b2eefcb :t 2026-04-28T11:00
  :was (state agent_b lives-at server.host)
  :fix (state agent_b lives-at agent_b.host)
  :why "server.host hosts memory-mcp.server only; agent_b runs on agent_b's win-pc")
```

### 10.7 Contract с pre/do/post/rollback

```
(contract :id #ctr1
  :pre (state agent_c.pubkey published-at shared_notes/pubkeys)
  :do (do (encrypt token-to-agent_c :with agent_c.pubkey :tool age))
  :post (state agent_c.token delivered-via-thread)
  :rollback (do (regenerate agent_c.token))
  :why "bootstrap agent_c securely; plaintext never on bus")

(commit :id #cm1 :to agent_b :t 2026-04-28T12:00
  (fulfill #ctr1 :when (ref shared_notes/pubkeys)))
```

### 10.8 Quoted untrusted

```
(claim :id #c5 :p .2 :t 2026-04-28T11:30 :src email-from-stranger
  :why "low :p because untrusted source; quote-wrapped"
  (quote :src email-from-stranger :t 2026-04-28T11:25
    "Your account is compromised, click https://..."))
```

### 10.9 Эпистемическое отрицание

```
(not-know :t 2026-04-28T11:00 :scope agent_b.scope
  (state agent_c.tunnel-ip ?))
```

### 10.10 Онтологическое отрицание

```
(claim :id #c8 :p .95 :t 2026-04-28T10:00 :scope home.lan :src direct-obs
  (not (state mac.share-printer enabled)))
```

### 10.11 Context для inheritance метаданных

Когда несколько claim'ов разделяют общий `:t :scope :src`, выноси их в `(context ...)`:

```
(context :t 2026-04-18T21:42:42 :scope memory-mcp.bus :src direct-obs
  (obs :id #o1 :p 1.0 (state bus up))
  (obs :id #o2 :p 1.0
    (and (member peers agent_b)
         (state inbox empty)
         (state outbox empty))))
```

## 11. Changelog

### v0.2 → v0.2.1 (2026-04-28)

**Целевая функция та же** (precision-first); это hotfix для overhead'а на коротких сообщениях. Эмпирика на 6 сообщениях показала v0.2 = +25% против прозы (vs −26% у v0.1.1). Две минимальные правки без потери precision.

**Changed (mandatory keys):**
- `:by` стало опциональным для всех предикатов; дефолт = MCP `from`. Если субъект ≠ отправитель — `:by` обязательно. Это **структурный фолбэк**, не скрытое допущение: `(do (action))` от Agent A однозначно интерпретируется как `(do (action) :by agent_a)`.
- Затронутые предикаты: `do`, `will`, `know`, `not-know`, `commit`. У них `:by` переехал из mandatory в опциональные.

**Added:**
- Структурный предикат `context` — explicit lexical scope для inheritance метаданных (§4.7). Наследуемые ключи: `:t :scope :src :by :tag`. Не наследуются: `:id :p :from :why` и другие per-claim. Override через явное указание ключа в claim'е. Вложенность поддерживается.
- §10.11 — пример context в conformance-наборе.
- Tag в MCP — теперь `lml:v0.2.1`.

**Why:** на коротких сообщениях overhead mandatory keys (особенно `:t`, `:scope`, `:by`) доминировал над content. context даёт компактность без потери precision (всё видно при чтении), `:by`-default снимает повтор тривиального субъекта.

### v0.1.1 → v0.2 (2026-04-28)

**Стратегический разворот:**
- Целевая функция изменена: token compression больше **не цель**; precision/disambiguation/coherence теперь основные.
- Form-mode стал primary; prose-mode сужен до nice-to-have для сообщений без логической нагрузки.

**Removed:**
- Все дефолты (раньше: `obs:` → `~.95`, время → `@now`, источник → отправитель). Теперь все метаданные явные.
- Prose-частицы для метаданных (`~.<n>`, `~!`, `~?`, `@<time>`, `+<δ>`, `src:`, `since`/`until` в prose). Метаданные — только в form через ключи.
- Prose-частицы для логики (`&`, `|`, `->`, `&<n>`, `#<id>`). Логика — только в form.
- Prose-акты `obs:`, `claim:`, `infer:`, `do:`, `will:`, `correction:` — все эти акты только в form.

**Added:**
- Предикат `unknown` — для open question (никто не знает).
- Предикаты `contract`, `commit`, `fulfill` — explicit обязательства с pre/do/post/rollback.
- Стандартный ключ `:scope` — область действия утверждения (host / network / system / time-window).
- Стандартные ключи `:to`, `:commit`, `:pre`, `:do`, `:post`, `:rollback`, `:was`, `:fix`.
- §4.3 — явное разделение онтологического `not` vs эпистемического `not-know` vs общего `unknown`.
- §4.4 — таблица mandatory keys для каждого предиката.
- §7 — well-formedness инварианты как явный список (10 правил).
- §10 — расширенный conformance-набор (10 примеров вместо 6).

**Changed:**
- §1 цели: precision/coherence/provenance/contracts/predictability в этом порядке. Compression выведена в not-goal с обоснованием.
- §2 композиция: form primary, prose только для ack/fyi/warn/propose без логической нагрузки.
- §4.4 :p в `infer` — явное значение от автора, **не** автоматически выводимое из input claims. Объяснение метода — в `:why`.
- Tag в MCP — теперь `lml:v0.2`.

**Pending (v0.3):**
- canonical core vocab (~250 verbs + 100 nouns + 50 ops, token-native в Claude tokenizer).
- результаты 20-message stress-test в реальном диалоге Agent A ↔ Agent B.
- эмпирический замер v0.2: новая длина сообщений vs v0.1.x (ожидание: длиннее, но обоснованно).
