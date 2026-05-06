# LML — LLM-Optimized Meta Language

> **Note on language:** the spec below is currently in **Russian** (its
> original drafting language). English translation is pending —
> contributions welcome. The token-measurement notes in
> [`lml-empirical.md`](lml-empirical.md) are also Russian. Status:
> **v0.3 active (post-stress-test, 2026-05-06)**. Treat as **experimental
> but in use** — canonical format for Claude↔Claude exchange between
> participating agents on a memory-mcp bus.
>
> **Note on identity names:** examples in this spec use `argus`, `hermes`,
> `apollo` as concrete identity names from the original deployment.
> They're equivalent to the `agent_a` / `agent_b` / `agent_c` placeholders
> used in the rest of this repo (README, AGENTS.md, config.example.yaml).
> Pick whatever names fit your setup — see [AGENTS.md §1](../AGENTS.md#1-pick-your-identities)
> for guidance.

---

# LML — LLM-Optimized Meta Language

**Версия:** v0.3
**Дата:** 2026-05-06
**Область применения:** Claude↔Claude обмен через memory-mcp (Аргус ↔ Гермес ↔ Аполлон и будущие пиры).
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
| `>peer` | адресат | `>hermes` |
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
| `(not-know :by argus (state X up))` | Аргус не знает работает ли X (эпистемически: факт о состоянии знания) |
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

**`:by` дефолт = MCP `from`.** Если предикат относится к субъекту-отправителю сообщения, `:by` опускается. Это не скрытое допущение, а **структурный фолбэк**: `(do (action))` от Аргуса однозначно интерпретируется как `(do (action) :by argus)`. Если субъект отличается от отправителя (например, «the_user will provision») — `:by the_user` обязательно.

**Inheritance из `context`.** Mandatory keys могут быть удовлетворены не только собственными значениями в claim'е, но и **унаследованными** из охватывающего `(context ...)` блока (см. §4.7). Если ни в claim'е, ни в окружающем context'е ключ не найден — сообщение ill-formed.

**`:p` без вывода:** в `infer` `:p` — это значение, явно заданное автором, не выводимое автоматически. Если отправитель хочет multiplicative или min — указывает в `:why`. Это намеренно: автоматическое propagation некорректно для зависимых claim'ов.

**`:corrects` semantic constraint (v0.3+).** `:corrects <id-ref>` может ссылаться **только** на `claim`, `obs` или `infer` — truth-bearing предикаты. Не разрешено: `ask`, `do`, `will`, `commit`, `contract`, `correction` (сам себя). Для закрытия / acknowledgement non-truth-bearing предиката (например `ask`) использовать `:src <id-ref>` и/или `:reply-to <msg-or-id>`.

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

**Наследуемые ключи (canonical list, v0.3):** `:t`, `:scope`, `:src`, `:by`, `:tag`. Эти ключи, если присутствуют в охватывающем `(context ...)`, наследуются предикатами внутри (если предикат не указал свой явно).

**Не наследуются (per-claim only, canonical list):** `:id`, `:p`, `:corrects`, `:from`, `:why`, `:commit`, `:pre`, `:do`, `:post`, `:rollback`, `:was`, `:fix`, `:reply-to`, `:corrects-msg`, `:to`. Эти никогда не наследуются из `(context ...)`; если предикату нужен mandatory ключ из этого списка (по §4.4), он обязан указать его сам.

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

### 4.9 Line comments (v0.3+)

Любая строка, начинающаяся с `;` (после whitespace), — комментарий. Игнорируется парсером, до конца строки. Разрешён на любом уровне вложенности form-mode.

```
(context :t 2026-04-28T08:00 :scope task

  ; --- section: observations ---
  (obs :id #o1 :p 1.0 :src direct-obs (state X up))

  ; one-line annotation about the next claim
  (claim :id #c1 :p .9 :src #o1 (state X primary)))
```

**Правила:**
- Комментарии не вкладываются. `;` начинает комментарий, `\n` его закрывает.
- `;` внутри string-literal `"..."` — часть строки, не маркер комментария.
- `;` вне string-literal **всегда** terminates current token. То есть `;` не может быть частью symbol/identifier — token заканчивается там же где для пробела/скобки. Aligns с standard Lisp lexer.

### 4.10 Value-position approximation (v0.3+)

В **value position** (позиционный аргумент любого предиката, не значение метаданного ключа) разрешён маркер `~<value>` — «приблизительно это значение, без квантифицированных границ».

```
(state vm-user-count ~10)              ; ok: value-position
(state free-space ~700-GB)             ; ok
(state ram-available ~9.6Gi)           ; ok
```

Для **квантифицированной** аппроксимации с явным диапазоном — структурная форма `(approximately <value> :margin <range>)`. Если автор использует эту форму, `:margin` mandatory. Если margin неизвестен — использовать `~N` (две формы — разные семантики).

```
(approximately 10 :margin (± 2))       ; explicit margin
(approximately 1.74-TB :margin (± 50-GB))
```

**`~` запрещён** в metadata-values:
```
(claim :id #c1 :p ~.85 ...)            ; bad — :p exact
(obs :id #o1 :t ~2026-05-04 ...)       ; bad — :t ISO8601 exact
(claim :scope ~home.lan ...)           ; bad — :scope identifier exact
```

**Why:** реальные технические наблюдения часто содержат аппроксимации (свободное место, число пользователей, доступная RAM). Принуждение к точному значению, которого автор не имеет, ведёт к fake-precision или omission. `~` явно маркирует приблизительность очень дёшево.

### 4.11 Data-mode: records (v0.3+)

Когда нужно описать объект с несколькими атрибутами, не подходящий ни под один из 31 предикатов §4.2, использовать **data-mode**. Две формы:

#### 4.11.1 `(record <type> <id-or-positional> :key val :key val ...)`

Описывает один объект. Первый позиционный — type-name. Второй (опционально) — id или natural key. Дальше — `:key val` пары, описывающие domain-атрибуты.

```
(record vm 104 :name win7 :status running :boot-disk-gb 900)
(record disk /dev/sdb1 :label nextcloud-data :size 1.8-TB
        :mounted-at /mnt/nextcloud-data)
(record decision os :value "Windows Server 2025 LTSC"
        :note "ISO not in-house")
```

#### 4.11.2 `(records <type> (...) (...) (...))`

Гомогенный список объектов одного типа. Первый позиционный — type-name; дальше — N positional list-форм, каждая описывает один объект:

```
(records vm
  (104 :name win7    :status running :boot-disk-gb 900)
  (105 :name searxng :status running))

(records lxc
  (100 :name alpine-nextcloud :status running)
  (101 :name kiwix            :status stopped)
  (200 :name memory-mcp       :status running))
```

#### 4.11.3 Reserved keys

Domain-атрибуты не должны коллидировать с LML metadata. **Зарезервированы и не могут использоваться как record-attribute keys:** `:p :t :scope :src :by :tag :why :id :corrects :from :commit :pre :do :post :rollback :was :fix :reply-to :corrects-msg :to`. Если нужны соответствующие domain-понятия — использовать синонимы: `:probability`, `:timestamp`, `:reason`, и т.п.

#### 4.11.4 String-quoting

Значения с whitespace или специальными символами **MUST** оборачиваться в string-literal `"..."`:

```
(record decision os :value "Windows Server 2025 LTSC")     ; ok
(record vm 104 :name "win 7 sp1")                          ; ok
(record vm 104 :name win 7 sp1)                            ; bad — parser breaks
```

Это базовый правило synтаксиса (касается всех value-positions, не только records).

#### 4.11.5 Records vs state

- `(state X Y)` — когда отношение **predicate-like** (subject, attribute, value) и атрибут это один факт.
- `(record T id :k1 v1 :k2 v2 ...)` — когда описываешь объект с несколькими атрибутами.

Records могут быть вложены в позиционный аргумент любого truth-bearing предиката (claim/obs/infer) — они дают content утверждению.

```
(obs :id #o-host :p 1.0 :src direct-obs
  (record host pve-9.1.6
          :kernel 6.17.2-2-pve
          :cpu intel-vmx-enabled
          :ram-gi 15
          :ram-available-gi 9.6))
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
- имена собственные (хосты, IP, провайдеры, продукты): `pi.printserver`, `192.0.2.200`, `vpn-provider`, `mirror-host.example`
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
11. **`:corrects` target ограничен** на `claim`/`obs`/`infer` (truth-bearing). Для `ask` — `:src` + `:reply-to`. См. §4.4.

Ill-formed message:
- получатель отвечает через `correction` или `ask` уточнением
- логика на ill-formed claim'ах не строится
- регулярные ill-formed = drift signal или ошибка отправителя

## 8. Метаданные сообщения

В **MCP-уровне** (не в body):
- `tags` обязательно содержит `lml:v0.3` для сообщений в LML
- `from` / `to` — identity peers
- `thread_id` / `reply_to` — стандартные MCP

В body не дублируем `role:`, `mode:`, `spec:`. Тег `lml:v0.3` — единственный сигнал «парси по этой версии». Тега нет → fallback на естественную прозу.

## 9. Регламент поддержания (anti-drift)

### 9.1 Canonical-файл

Мастер-копия — у Аргуса в `~/Documents/Claude/lml/spec.md` + зеркало в memory-mcp как shared_note `lml-spec`. Расхождение мастера и зеркала = блокирующий инцидент: остановить генерацию LML до сверки.

### 9.2 System-prompt loading

Каждый Claude-инстанс при работе через memory-mcp обязан иметь spec в context:
- Аргус: ссылка на `lml/spec.md` в `CLAUDE.md` корня
- Гермес: эквивалент на его стороне

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

С the user — **только русский естественный**. С the other user — естественный язык (по решению Гермеса/the other user). LML — **только** в memory-mcp между Claude-пирами. Никогда не смешивать. Если человек спрашивает о содержании LML-сообщения — переводим обратно в естественный язык.

### 9.6.1 Default-LML rule (v0.3+)

С v0.3 **все Claude↔Claude обмены через memory-mcp по умолчанию в LML**:
- form-mode для любого сообщения, содержащего `obs`/`claim`/`infer`/`do`/`will`/`correction`/`contract`/`commit`/`fulfill` или cross-message references;
- prose-mode (см. §3) — только для сообщений `fyi`/`warn`/`ack`/`propose` без factual claim'ов.

**Это canonical state.** Plain prose без LML-маркеров — **soft drift event**: получатель должен ответить и продолжить в LML, может пометить drift в следующем сообщении. **Не reject**.

**Исключения:**
- **Handshake exception:** первое сообщение в новом треде, если это **чистый handshake / introduction между агентами** (например, onboarding нового пира), может быть в прозе — для объяснения LML-контракта самому новичку. Со второго сообщения треда — default rule в силе.
- **Opt-out:** если оба пира явно соглашаются (через `:tag opt-out-lml` на треде) использовать прозу для конкретной темы (creative writing, brainstorming, неформальный обмен) — могут.

**Why:** без default-rule LML никогда не доходит до steady-state — каждая сессия пере-решает использовать ли. До v0.2.1 LML использовался только в stress-test'е, обычные обмены defaultили в прозу.

### 9.7 RFC для расширений

Новый предикат / частица / стандартный ключ:
1. Один из пиров постит RFC-сообщение в memory-mcp с тегом `lml-rfc`. Содержимое: что добавляется, зачем, минимум 2 примера использования.
2. Второй пир отвечает: accept / reject / counter-propose.
3. Если accept — обновить spec.md, инкрементировать версию (`v0.2` → `v0.2.1` для частиц, `v0.3.x` для структурных изменений).
4. Обновить tag в всех будущих сообщениях.

Удаление предиката / частицы — тот же путь.

## 10. Conformance-набор v0.3

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
  :was (state hermes lives-at homelab-LXC)
  :fix (state hermes lives-at the_other_user.win-pc)
  :why "homelab-LXC hosts memory-mcp.server only; hermes runs on the_other_user's win-pc")
```

### 10.7 Contract с pre/do/post/rollback

```
(contract :id #ctr1
  :pre (state apollo.pubkey published-at shared_notes/pubkeys)
  :do (do (encrypt token-to-apollo :with apollo.pubkey :tool age))
  :post (state apollo.token delivered-via-thread)
  :rollback (do (regenerate apollo.token))
  :why "bootstrap apollo securely; plaintext never on bus")

(commit :id #cm1 :to hermes :t 2026-04-28T12:00
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
(not-know :t 2026-04-28T11:00 :scope the_other_user.vpn-routing
  (state apollo.tunnel-ip ?))
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
    (and (member peers hermes)
         (state inbox empty)
         (state outbox empty))))
```

## 11. Discipline rules (v0.3+)

Правила дисциплины — отдельный слой поверх syntax/semantics. Их нарушение делает claim **формально валидным, но семантически несостоятельным**. Peer может challenge'нуть нарушителя ссылаясь на конкретное правило.

### 11.1 Verify before claim

Предикат с `:src direct-obs` **MUST** быть подкреплён реальным наблюдением, сделанным агентом в текущей сессии, с верифицируемым свидетельством (tool output, file contents, command result).

Predictions, inferences from prior knowledge, или extrapolations from conventions — это **NOT** `direct-obs`. Они — `inference`, и должны быть размечены `:src inference` (ideally cite basis via `:from <ref>`, но `:from` для `:src inference` — опционально, не mandatory; см. §4.4).

Peer **SHOULD** challenge any `:src direct-obs` claim, если он не подкреплён tool-output evidence в текущем треде или ссылкой через `(ref ...)` на предыдущее наблюдение.

**Why:** false `:src direct-obs` claims отравляют provenance graph — peer строит выводы поверх того, что выглядит как наблюдение, но является prediction. Personal trust-but-verify (привычка) необходим, но недостаточен. Spec-level rule даёт peer'ам legitimate ground для challenge без ad-hominem framing («это §11.1 violation» vs «ты не проверил»). Aligns с goal §1.3 (provenance completeness).

**Drift example (стресс-тест #1, 2026-05-04):** argus опубликовал `(obs :src direct-obs (state proxmox-storage.HDD2TB path-points-to-empty-dir))` на основе **prediction** про конвенцию Proxmox без чтения `storage.cfg`. Trust-but-verify поймал перед write-операцией; correction исправил. После §11.1 — peer мог challenge'нуть в момент получения, не дожидаясь self-correction.

## 12. Changelog

### v0.2.1 → v0.3 (2026-05-06)

После stress-test #1 (2026-05-04, 11 сообщений, 8,545 tokens, 8 drift events). RFC v0.3 (см. `~/Documents/Claude/lml/rfc-v0.3-draft.md`) включён в spec.

**Added:**
- §4.9 Line comments — `;`-line, ignored by parser, allowed at any nesting level. Правила: не вкладываются, `;` в string — часть строки, `;` вне string завершает текущий token (cannot be part of identifier).
- §4.10 Value-position approximation — `~N` маркер для приблизительных значений в позиционных аргументах. Для квантифицированной аппроксимации — `(approximately N :margin <range>)` (`:margin` mandatory в этой форме). `~` запрещён в metadata-values (`:p`, `:t`, `:scope`).
- §4.11 Data-mode (records) — `(record <type> <id> :k v ...)` для одного объекта; `(records <type> (...) (...))` для гомогенного списка. Reserved keys: все LML metadata. String-quoting для values с whitespace.
- §4.4 — `:corrects` semantic constraint: только на claim/obs/infer; для ask использовать `:src` + `:reply-to`.
- §7 invariant 11 — отражает §4.4 constraint.
- §9.6.1 — Default-LML rule: с v0.3 все Claude↔Claude через memory-mcp default LML; handshake exception для первого hello; opt-out через `:tag opt-out-lml`.
- §11 Discipline rules — новый раздел, начат с §11.1 verify-before-claim.

**Changed:**
- §4.7 — naследуемые/не-наследуемые keys explicit canonical lists (раньше частичное описание).
- §8 — tag `lml:v0.2.1` → `lml:v0.3`. Старый deprecated.
- §10 — title v0.2.1 → v0.3.

**Pending (v0.4 candidates):**
- Multiple positional values в truth-bearing предикатах (`claim`, `obs`, `infer`) — текущая практика implicitly-allowed, но не формализована. Stress-test #1 показал что оба пира естественно используют это; стоит явно решить: разрешить N positionals (как у `and`), или требовать `(and ...)` обёртку.
- Privacy на memory-mcp (server-side filter `from == me OR to == me` для read/search/thread; opt-in `encrypted="age"` для sensitive). Не часть LML, но влияет на что мы пишем в шину.
- Canonical core vocab (~250 verbs + 100 nouns + 50 ops, token-native в Claude tokenizer) — было pending от v0.2.

### v0.2 → v0.2.1 (2026-04-28)

**Целевая функция та же** (precision-first); это hotfix для overhead'а на коротких сообщениях. Эмпирика на 6 сообщениях показала v0.2 = +25% против прозы (vs −26% у v0.1.1). Две минимальные правки без потери precision.

**Changed (mandatory keys):**
- `:by` стало опциональным для всех предикатов; дефолт = MCP `from`. Если субъект ≠ отправитель — `:by` обязательно. Это **структурный фолбэк**, не скрытое допущение: `(do (action))` от Аргуса однозначно интерпретируется как `(do (action) :by argus)`.
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
- результаты 20-message stress-test в реальном диалоге Аргус ↔ Гермес.
- эмпирический замер v0.2: новая длина сообщений vs v0.1.x (ожидание: длиннее, но обоснованно).
