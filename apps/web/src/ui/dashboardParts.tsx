import { useState } from 'react'
import type { LinkFields, LinkResult } from '../hooks/useAccountShell'
import type { Me, SourceStatus, SourcesStatus } from '../types'
import { Checkbox } from './authFormParts'
import { formatRelativeTime } from './dateFormat'

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '??'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

export function Avatar({ name, size }: { name: string; size: number }) {
  return (
    <div className="home-avatar" style={{ width: size, height: size, fontSize: size * 0.36 }}>
      {initials(name)}
    </div>
  )
}

/** Реальное состояние источника, не только «настроена привязка».
 * `session_cached`/`last_verified_at` приходят из БД честно — это не живая
 * проверка прямо сейчас (лишний логин — лишний шанс на капчу, см.
 * apps/api/main.py::sources_status), а факт «когда мы последний раз
 * реально подтвердили доступ» (переиспользованием кук или свежим входом).
 * "on" здесь означает именно это, не просто «есть сохранённый пароль». */
function sourceState(status: SourceStatus | undefined): {
  on: boolean
  label: string
} {
  if (status === undefined) return { on: false, label: '…' }
  if (!status.linked) return { on: false, label: 'Не подключено' }
  if (status.circuit_open) return { on: false, label: 'Нужен вход' }
  if (!status.session_cached) return { on: false, label: 'Не проверено' }
  return { on: true, label: 'Активен' }
}

export function StatusDot({ label, status }: { label: string; status: SourceStatus | undefined }) {
  const { on, label: text } = sourceState(status)
  return (
    <div className="home-status-row">
      <span className={`home-status-dot${on ? '' : ' is-off'}`} />
      <span className="home-status-text">
        {label}:{' '}
        <span className={`home-status-value${on ? '' : ' is-off'}`}>{text}</span>
      </span>
    </div>
  )
}

const LINK_LABELS: Record<'sush' | 'edupage', { school: string; username: string; schoolHint: string }> = {
  sush: { school: 'Школа (код)', username: 'ИИН', schoolHint: 'например ptr' },
  edupage: { school: 'Поддомен школы', username: 'Логин', schoolHint: 'например nispetropavlovsk' },
}

function LinkForm({
  source,
  onLink,
}: {
  source: 'sush' | 'edupage'
  onLink: (source: 'sush' | 'edupage', fields: LinkFields) => Promise<LinkResult>
}) {
  const [school, setSchool] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ text: string; kind: 'error' | 'warning' } | null>(null)
  const labels = LINK_LABELS[source]

  async function submit() {
    if (!school.trim() || !username.trim() || !password || !consent || busy) return
    setBusy(true)
    setMessage(null)
    const result = await onLink(source, { school: school.trim(), username: username.trim(), password })
    setBusy(false)
    if (!result.ok) {
      setMessage({ text: result.error ?? 'Не получилось привязать', kind: 'error' })
      return
    }
    setPassword('')
    if (result.sessionOk === false) {
      setMessage({ text: result.reason ?? 'нужен ручной вход', kind: 'warning' })
    }
    // sessionOk === true: статус сам обновится на "Подключено", форма исчезнет
  }

  const disabled = !school.trim() || !username.trim() || !password || !consent || busy

  return (
    <div className="home-settings-linkform">
      <div className="home-settings-field">
        <span className="home-settings-field-label">{labels.school}</span>
        <input
          type="text"
          className="home-settings-input"
          value={school}
          onChange={(e) => setSchool(e.target.value)}
          placeholder={labels.schoolHint}
        />
      </div>
      <div className="home-settings-field">
        <span className="home-settings-field-label">{labels.username}</span>
        <input
          type="text"
          className="home-settings-input"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </div>
      <div className="home-settings-field">
        <span className="home-settings-field-label">Пароль</span>
        <input
          type="password"
          className="home-settings-input"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <p className="home-settings-consent-text">
        Nis3 не связан с НИШ. Пароль шифруется и используется только для входа в {source === 'sush' ? 'СУШ' : 'EduPage'} от твоего имени — отвязать источник и удалить пароль можно в любой момент.
      </p>
      <Checkbox
        checked={consent}
        onToggle={() => setConsent((v) => !v)}
        label="Понимаю и согласен(на)"
        labelFontSize={12.5}
      />
      {message && (
        <div className={message.kind === 'error' ? 'home-settings-msg-error' : 'home-settings-msg-warning'}>
          {message.text}
        </div>
      )}
      <button type="button" className="home-settings-linkbtn" onClick={submit} disabled={disabled}>
        {busy ? 'Привязываем…' : 'Привязать'}
      </button>
    </div>
  )
}

function SourceSettingsCard({
  name,
  source,
  status,
  onUnlink,
  onLink,
}: {
  name: string
  source: 'sush' | 'edupage'
  status: SourceStatus | undefined
  onUnlink: () => void
  onLink: (source: 'sush' | 'edupage', fields: LinkFields) => Promise<LinkResult>
}) {
  const linked = status?.linked ?? false
  const { on, label: statusLabel } = sourceState(status)
  return (
    <div className="home-settings-group">
      <span className="home-settings-label">{name}</span>
      <div className="home-settings-box">
        <div className="home-status-row">
          <span className={`home-status-dot${on ? '' : ' is-off'}`} />
          <span className="home-status-text">
            Статус: <span className={`home-status-value${on ? '' : ' is-off'}`}>{statusLabel}</span>
          </span>
        </div>
        {linked ? (
          <>
            <div className="home-settings-field">
              <span className="home-settings-field-label">
                {name === 'СУШ' ? 'Школа' : 'Логин'}
              </span>
              <div className="home-settings-field-value">{status?.school || status?.username}</div>
            </div>
            <div className="home-settings-field">
              <span className="home-settings-field-label">Сессия</span>
              <div className="home-settings-field-value">
                {status?.session_cached && status.last_verified_at
                  ? `Подтверждена: ${formatRelativeTime(status.last_verified_at)}`
                  : 'Ещё не подтверждалась'}
              </div>
            </div>
            <button type="button" className="home-settings-danger" onClick={onUnlink}>
              Отключить {name}
            </button>
          </>
        ) : (
          <LinkForm source={source} onLink={onLink} />
        )}
      </div>
    </div>
  )
}

export function SettingsPanelBody({
  me,
  sources,
  onUnlink,
  onLink,
  onLogout,
}: {
  me: Me | null
  sources: SourcesStatus | null
  onUnlink: (source: 'sush' | 'edupage') => void
  onLink: (source: 'sush' | 'edupage', fields: LinkFields) => Promise<LinkResult>
  onLogout: () => void
}) {
  return (
    <>
      <div className="home-settings-profile">
        <Avatar name={me?.display_name ?? '??'} size={52} />
        <div>
          <div className="home-settings-name">{me?.display_name ?? '…'}</div>
          <div className="home-settings-sub">Ученик Nis3</div>
        </div>
      </div>

      <div className="home-settings-group">
        <span className="home-settings-label">Аккаунт</span>
        <div className="home-settings-box">
          <div className="home-settings-field">
            <span className="home-settings-field-label">Имя</span>
            <div className="home-settings-field-value">{me?.display_name}</div>
          </div>
          <div className="home-settings-field">
            <span className="home-settings-field-label">Email</span>
            <div className="home-settings-field-value">{me?.email}</div>
          </div>
        </div>
      </div>

      <SourceSettingsCard
        name="EduPage"
        source="edupage"
        status={sources?.edupage}
        onUnlink={() => onUnlink('edupage')}
        onLink={onLink}
      />
      <SourceSettingsCard
        name="СУШ"
        source="sush"
        status={sources?.sush}
        onUnlink={() => onUnlink('sush')}
        onLink={onLink}
      />

      <button type="button" className="home-settings-logout" onClick={onLogout}>
        Выйти из аккаунта
      </button>
    </>
  )
}
