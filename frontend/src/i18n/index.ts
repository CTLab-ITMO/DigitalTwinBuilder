import { ref } from 'vue'

/**
 * A two-language dictionary, deliberately without a dependency: the app has no
 * test framework and `vue-tsc` is the only automated gate, so the type system
 * carries the weight. `en` is the canonical key set — a missing or extra Russian
 * key is a compile error, and `t()` rejects a key that is not in the dictionary.
 *
 * Proper nouns and technical names are the same string in both languages and
 * stay untranslated: SQL, SimPy, PyChrono, DES, KPI, WIP, PostgreSQL, API,
 * Digital Twin Builder, `Agent {i}`.
 */
const en = {
  'app.title': 'Digital Twin Builder',
  'tab.interview': 'Interview',
  'tab.database': 'Database',
  'tab.twin': 'Digital Twin',
  'tab.settings': 'Settings',
  'common.generating': 'Generating...',

  'sidebar.sessions': 'Sessions',
  'sidebar.newChat': '+ New Chat',
  'sidebar.empty': 'No sessions yet',
  'sidebar.chat': 'Chat {id}',
  'sidebar.rename': 'Rename',
  'sidebar.delete': 'Delete',
  'sidebar.confirmDelete':
    'Delete session "{title}"? All of its conversations and messages will be deleted with it.',
  'sidebar.agent': 'Agent {i}',
  'agent.status.idle': 'idle',
  'agent.status.busy': 'busy',
  'agent.status.offline': 'offline',

  'interview.title': 'Building a manufacturing digital twin',
  'interview.completed': '✓ Interview complete',
  'interview.completedHint': 'Go to the "Database" tab',
  'interview.failed': "The agent's reply could not be parsed",
  'interview.failedHint':
    'Attempts: {n}. Below is what exactly is wrong; send the message again so the agent answers anew.',
  'interview.processing': 'Processing...',
  'interview.repair': 'reply not parsed, repair {n}',
  'interview.placeholder': 'Enter information about your production...',
  'interview.send': 'Send',
  'interview.temperature': 'Temperature',
  'interview.maxTokens': 'Max Tokens',

  'db.title': 'Database setup',
  'db.needInterview': 'Please complete the interview on the "Interview" tab',
  'db.interviewResult': 'Interview result',
  'db.generate': 'Generate DB schema',
  'db.checking': 'Schema check',
  'db.checkingHint':
    'The agent generates a schema, it is validated as PostgreSQL, and a repair is requested on error. This may take a few minutes.',
  'db.ok': 'Schema validated',
  'db.bad': 'Schema failed validation',
  'db.attempts': 'Attempts: {attempts}, repairs: {repaired}',
  'db.tables': '— tables: {tables}, views: {views}',
  'db.schema': 'Database schema',

  'twin.title': 'Digital twin configuration',
  'twin.needDb': '⚠️ Please complete the database setup',
  'twin.sqlHeading': 'SQL code for the DB',
  'twin.viewSql': 'View SQL',
  'twin.downloadSql': 'Download SQL',
  'twin.generateConfig': 'Generate configuration',
  'twin.configHeading': 'Digital twin configuration',
  'twin.viewConfig': 'View twin configuration',
  'twin.simHeading': 'PyChrono simulation code',
  'twin.generateCode': 'Generate code',
  'twin.viewChrono': 'View PyChrono code',
  'twin.downloadCode': 'Download code',
  'twin.regenerate': 'Regenerate',
  'twin.desHeading': 'DES model (SimPy)',
  'twin.generateDes': 'Generate DES model',
  'twin.desRunning':
    'The model is generated, run, and sent back for repair on error — until it completes and prints the KPI.',
  'twin.attempt': 'Attempt {n}:',
  'twin.attemptGen': 'generation',
  'twin.attemptRepair': 'repair',
  'twin.chars': '{n} chars',
  'twin.attemptOk': '— runs and prints the KPI',
  'twin.attemptBad': '— failed ({status})',
  'twin.desOk': 'The model runs and reports the KPI',
  'twin.desBad': 'The model failed validation',
  'twin.attemptsRepairs': 'attempts {attempts}, repairs {repaired}.',
  'twin.viewSimpy': 'View SimPy code',
  'twin.noReply': 'The agent returned no reply',
  'kpi.throughput': 'Throughput',
  'kpi.wip': 'WIP',
  'kpi.energy': 'Energy / part',
  'unit.partsPerHour': 'parts/hour',
  'unit.parts': 'parts',
  'unit.kwhPerPart': 'kWh/part',

  'settings.title': 'Settings',
  'settings.agentStatus': 'Agent status',
  'settings.status': 'Status:',
  'settings.lastHeartbeat': 'Last heartbeat: {t}',
  'settings.queues': 'Task queues',
  'settings.pending': 'Pending: {n}',
  'settings.active': 'Active: {v}',
  'settings.yes': 'Yes',
  'settings.no': 'No',
  'settings.apiHealth': 'API Health',
  'settings.database': 'Database: {v}',
  'settings.pool': 'Pool: {v}',

  'error.createSession': 'Could not create a session — check the API',
  'error.createConversation': 'Could not create a conversation — check the API',
  'error.jsonParse': "The agent's reply could not be parsed as JSON — ask it to repeat or fix it.",
  'error.jsonParseShort': "The agent's reply could not be parsed as JSON — ask it to repeat.",
  'error.jsonParseFinal':
    "The agent's reply could not be parsed as JSON after several attempts — ask it to repeat or fix it.",
  'error.dbTimeout': 'Timed out waiting for schema generation',
  'error.dbError': 'Schema generation error',
  'error.desTimeout': 'Timed out waiting for DES model generation',
  'error.desError': 'DES model generation error',
  'error.agentTimeout': "Timed out waiting for the agent's reply",
  'error.agentError': "Agent reply processing error",
  'error.generationError': 'Generation error',
  'error.noReply': 'The agent returned no reply',
}

export type MessageKey = keyof typeof en

const ru: Record<MessageKey, string> = {
  'app.title': 'Digital Twin Builder',
  'tab.interview': 'Интервью',
  'tab.database': 'База данных',
  'tab.twin': 'Цифровой двойник',
  'tab.settings': 'Настройки',
  'common.generating': 'Генерация...',

  'sidebar.sessions': 'Сессии',
  'sidebar.newChat': '+ Новый чат',
  'sidebar.empty': 'Сессий пока нет',
  'sidebar.chat': 'Чат {id}',
  'sidebar.rename': 'Переименовать',
  'sidebar.delete': 'Удалить',
  'sidebar.confirmDelete':
    'Удалить сессию «{title}»? Вместе с ней удалятся все её диалоги и сообщения.',
  'sidebar.agent': 'Агент {i}',
  'agent.status.idle': 'свободен',
  'agent.status.busy': 'занят',
  'agent.status.offline': 'офлайн',

  'interview.title': 'Создание цифрового двойника производства',
  'interview.completed': '✓ Интервью завершено',
  'interview.completedHint': 'Перейдите на вкладку «База данных»',
  'interview.failed': 'Ответ агента не удалось разобрать',
  'interview.failedHint':
    'Попыток: {n}. Ниже — что именно не так; отправьте сообщение ещё раз, чтобы агент ответил заново.',
  'interview.processing': 'Обработка...',
  'interview.repair': 'ответ не разобран, исправление {n}',
  'interview.placeholder': 'Введите информацию о вашем производстве...',
  'interview.send': 'Отправить',
  'interview.temperature': 'Температура',
  'interview.maxTokens': 'Макс. токенов',

  'db.title': 'Настройка базы данных',
  'db.needInterview': 'Пожалуйста, завершите интервью на вкладке «Интервью»',
  'db.interviewResult': 'Результат интервью',
  'db.generate': 'Сгенерировать схему БД',
  'db.checking': 'Проверка схемы',
  'db.checkingHint':
    'Агент генерирует схему, она проверяется как PostgreSQL, и при ошибке запрашивается исправление. Это может занять несколько минут.',
  'db.ok': 'Схема проверена',
  'db.bad': 'Схема не прошла проверку',
  'db.attempts': 'Попыток: {attempts}, исправлений: {repaired}',
  'db.tables': '— таблиц: {tables}, представлений: {views}',
  'db.schema': 'Схема базы данных',

  'twin.title': 'Конфигурация цифрового двойника',
  'twin.needDb': '⚠️ Пожалуйста, завершите настройку базы данных',
  'twin.sqlHeading': 'SQL код для БД',
  'twin.viewSql': 'Просмотр SQL',
  'twin.downloadSql': 'Скачать SQL',
  'twin.generateConfig': 'Сгенерировать конфигурацию',
  'twin.configHeading': 'Конфигурация цифрового двойника',
  'twin.viewConfig': 'Посмотреть конфигурацию ЦД',
  'twin.simHeading': 'Код симуляции PyChrono',
  'twin.generateCode': 'Сгенерировать код',
  'twin.viewChrono': 'Просмотр кода PyChrono',
  'twin.downloadCode': 'Скачать код',
  'twin.regenerate': 'Перегенерировать',
  'twin.desHeading': 'DES-модель (SimPy)',
  'twin.generateDes': 'Сгенерировать DES-модель',
  'twin.desRunning':
    'Модель генерируется, запускается и при ошибке отправляется на исправление — до тех пор, пока не завершится и не напечатает KPI.',
  'twin.attempt': 'Попытка {n}:',
  'twin.attemptGen': 'генерация',
  'twin.attemptRepair': 'исправление',
  'twin.chars': '{n} симв.',
  'twin.attemptOk': '— запускается и печатает KPI',
  'twin.attemptBad': '— не прошла ({status})',
  'twin.desOk': 'Модель запускается и сообщает KPI',
  'twin.desBad': 'Модель не прошла проверку',
  'twin.attemptsRepairs': 'попыток {attempts}, исправлений {repaired}.',
  'twin.viewSimpy': 'Просмотр кода SimPy',
  'twin.noReply': 'Агент не вернул ответ',
  'kpi.throughput': 'Пропускная способность',
  'kpi.wip': 'WIP',
  'kpi.energy': 'Энергия / деталь',
  'unit.partsPerHour': 'деталей/час',
  'unit.parts': 'деталей',
  'unit.kwhPerPart': 'кВт·ч/деталь',

  'settings.title': 'Настройки',
  'settings.agentStatus': 'Статус агентов',
  'settings.status': 'Статус:',
  'settings.lastHeartbeat': 'Последний сигнал: {t}',
  'settings.queues': 'Очереди задач',
  'settings.pending': 'В очереди: {n}',
  'settings.active': 'Активно: {v}',
  'settings.yes': 'Да',
  'settings.no': 'Нет',
  'settings.apiHealth': 'Состояние API',
  'settings.database': 'База данных: {v}',
  'settings.pool': 'Пул: {v}',

  'error.createSession': 'Не удалось создать сессию — проверьте API',
  'error.createConversation': 'Не удалось создать диалог — проверьте API',
  'error.jsonParse':
    'Ответ агента не удалось разобрать как JSON — попросите его повторить или исправить ответ.',
  'error.jsonParseShort': 'Ответ агента не удалось разобрать как JSON — попросите его повторить.',
  'error.jsonParseFinal':
    'Ответ агента не удалось разобрать как JSON после нескольких попыток — попросите его повторить или исправить ответ.',
  'error.dbTimeout': 'Превышено время ожидания генерации схемы',
  'error.dbError': 'Ошибка генерации схемы',
  'error.desTimeout': 'Превышено время ожидания генерации DES-модели',
  'error.desError': 'Ошибка генерации DES-модели',
  'error.agentTimeout': 'Превышено время ожидания ответа агента',
  'error.agentError': 'Ошибка обработки ответа агента',
  'error.generationError': 'Ошибка генерации',
  'error.noReply': 'Агент не вернул ответ',
}

export type Locale = 'ru' | 'en'

const messages: Record<Locale, Record<MessageKey, string>> = { en, ru }

const STORAGE_KEY = 'dtb.locale'

function detectInitialLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'ru' || saved === 'en') return saved
  } catch {
    /* private mode — fall through to the browser language */
  }
  return navigator.language.toLowerCase().startsWith('en') ? 'en' : 'ru'
}

/** Reactive: every `t()` read in a template re-renders when this changes. */
export const locale = ref<Locale>(detectInitialLocale())

export function setLocale(next: Locale) {
  locale.value = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    /* private mode — the choice just does not outlive the tab */
  }
  document.documentElement.lang = next
}

/**
 * Look up a key for the current locale, substituting `{name}` placeholders.
 * The `?? key` fallbacks are unreachable with fully-typed dictionaries, but they
 * keep a hand-edited dictionary from rendering `undefined` into the UI.
 */
export function t(key: MessageKey, params?: Record<string, string | number>): string {
  let text: string = messages[locale.value][key] ?? messages.en[key] ?? key
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value))
    }
  }
  return text
}

/** The broker reports agent state as a lowercase English word; localise it. */
export function tAgentStatus(status?: string): string {
  const key: MessageKey =
    status === 'idle'
      ? 'agent.status.idle'
      : status === 'busy'
        ? 'agent.status.busy'
        : 'agent.status.offline'
  return t(key)
}

document.documentElement.lang = locale.value
