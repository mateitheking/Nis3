// Формы ответов нашего API — общие между экранами (Главная, Расписание,
// дальше). См. apps/api/main.py — держать в синхроне с реальными полями,
// не выдумывать.

export interface Me {
  student_id: string
  display_name: string
  email: string | null
}

export interface Lesson {
  period: number | null
  start: string | null
  end: string | null
  subject: string
  teachers: string[]
  classrooms: string[]
  is_cancelled: boolean
  // Только у своих записей (см. CustomEntry) — id для удаления, custom для
  // отличения от настоящих уроков EduPage при показе в одном списке/сетке.
  id?: string
  custom?: boolean
}

export interface CustomEntry {
  id: string
  subject: string
  teacher: string | null
  room: string | null
  period: number | null
  time_from: string | null
  time_to: string | null
}

export interface UpcomingEvent {
  kind: string
  badge: string
  title: string
  event_date: string
  subject_name: string | null
}

/** СОР/СОЧ/БЖБ на день — см. GET /api/schedule/exams. Всегда kind
 * "assessment", отдельного поля под это нет (в отличие от UpcomingEvent,
 * который мешает все виды событий вместе). */
export interface ExamEvent {
  event_date: string
  subject_name: string | null
  badge: string
  title: string
}

export interface NotificationItem {
  id: number
  kind: string // "assessment" | "school_event" | "meeting" | "message"
  badge: string
  title: string
  posted_at: string
  event_date: string | null
  author: string | null
}

export interface Consultation {
  title: string
  period_from: number | null
  period_to: number | null
  time_from: string | null
  time_to: string | null
}

export interface GradeTopic {
  name: string
  score: number
  max_score: number
}

export interface GradeEvaluation {
  kind: string
  weight: number
  earned: number
  possible: number
  topics: GradeTopic[]
}

export interface GradeSubject {
  journal_id: string
  name: string
  score: number
  mark: number // 0 = ещё не выставлена, см. apps/api/sources/sush.py::SubjectGrade.Mark
  evaluations: GradeEvaluation[]
}

export interface GradesResponse {
  subjects: GradeSubject[]
  note: string | null
}

export interface SourceStatus {
  linked: boolean
  connected: boolean
  circuit_open: boolean
  reason: string | null
  school: string | null
  username: string | null
  session_cached: boolean
  last_verified_at: string | null
}

export interface SourcesStatus {
  sush: SourceStatus
  edupage: SourceStatus
}
