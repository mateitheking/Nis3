/** Список школ НИШ и их коды поддоменов СУШ (sms.{value}.nis.edu.kz).
 * Источник — enis2 (packages/shared/src/config.ts), тот же список, которым
 * пользуется он сам для выпадающего меню школы. */
export const NIS_SCHOOLS: { value: string; label: string }[] = [
  { value: 'akt', label: 'Актау ХБН' },
  { value: 'akb', label: 'Актобе ФМН' },
  { value: 'fmalm', label: 'Алматы ФМН' },
  { value: 'hbalm', label: 'Алматы ХБН' },
  { value: 'ast', label: 'Астана ФМН' },
  { value: 'atr', label: 'Атырау ХБН' },
  { value: 'krg', label: 'Караганда ХБН' },
  { value: 'kt', label: 'Кокшетау ФМН' },
  { value: 'kst', label: 'Костанай ФМН' },
  { value: 'kzl', label: 'Кызылорда ХБН' },
  { value: 'pvl', label: 'Павлодар ХБН' },
  { value: 'ptr', label: 'Петропавловск ХБН' },
  { value: 'sm', label: 'Семей ФМН' },
  { value: 'tk', label: 'Талдыкорган ФМН' },
  { value: 'trz', label: 'Тараз ФМН' },
  { value: 'trk', label: 'Туркестан ХБН' },
  { value: 'ura', label: 'Уральск ФМН' },
  { value: 'ukk', label: 'Усть-Каменогорск ХБН' },
  { value: 'fmsh', label: 'Шымкент ФМН' },
  { value: 'hbsh', label: 'Шымкент ХБН' },
]
