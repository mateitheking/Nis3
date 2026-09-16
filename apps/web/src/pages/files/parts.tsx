import { useCallback, useRef, useState } from 'react'
import { DEFAULT_PHOTO_WIDTH } from './useFilesData'
import type { PhotoMeta } from './useFilesData'

const MIN_PHOTO_WIDTH = 80
const MAX_PHOTO_WIDTH = 420

export function AddTile({
  onPick,
  mobile,
  large,
}: {
  onPick: (file: File) => void
  mobile?: boolean
  large?: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  // Мобильный FAB и десктопный кружок в пустом состоянии — оба 56px
  // (см. files.css: .files-add-fab/.files-empty .files-add-circle), а
  // плитка в гриде с фото — 44px (.files-add-tile). Иконка должна расти
  // вместе с кружком (22px/18px по дизайну), а не только для mobile —
  // раньше пустое состояние на десктопе получало 56px кружок с иконкой
  // от маленькой 44px-плитки, и «+» выглядел потерянным в кружке.
  const big = mobile || large
  return (
    <>
      <button
        type="button"
        className={mobile ? 'files-add-fab' : 'files-add-tile'}
        onClick={() => inputRef.current?.click()}
        aria-label="Добавить фото"
        title="Добавить фото"
      >
        <span className="files-add-circle">
          <svg viewBox="0 0 24 24" fill="none" stroke="#0a0a0a" strokeWidth="2.4" width={big ? 22 : 18} height={big ? 22 : 18}>
            <path d="M12 5v14M5 12h14" />
          </svg>
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onPick(file)
          e.target.value = ''
        }}
      />
    </>
  )
}

/** Компактная кнопка «+ Добавить» для шапки десктопного стола — тот же
 * hidden-input приём, что и в AddTile, но без кружка: рядом с переключателем
 * «Редактировать» кружок на 44/56px выглядел бы тяжелее самого стола. */
function AddButton({ onPick }: { onPick: (file: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  return (
    <>
      <button type="button" className="files-add-pill" onClick={() => inputRef.current?.click()}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" width="14" height="14">
          <path d="M12 5v14M5 12h14" />
        </svg>
        Добавить
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onPick(file)
          e.target.value = ''
        }}
      />
    </>
  )
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

function DeleteButton({ onDelete }: { onDelete: () => void }) {
  return (
    <button
      type="button"
      className="files-tile-delete"
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation()
        onDelete()
      }}
      aria-label="Удалить"
      title="Удалить"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
        <path d="M6 6l12 12M18 6L6 18" />
      </svg>
    </button>
  )
}

/** Зеркально крестику — тот в верхнем правом углу, этот в нижнем (просьба
 * пользователя 16 сентября 2026). Возвращает ширину карточки к дефолтной,
 * позицию не трогает. */
function ResetSizeButton({ onReset }: { onReset: () => void }) {
  return (
    <button
      type="button"
      className="files-tile-reset"
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation()
        onReset()
      }}
      aria-label="Вернуть исходный размер"
      title="Вернуть исходный размер"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="12" height="12">
        <path d="M3 12a9 9 0 1 1 2.64 6.36" />
        <path d="M3 18v-6h6" />
      </svg>
    </button>
  )
}

/** Ручка изменения размера в углу карточки — тянуть по горизонтали. Только
 * ширина: высота у карточки без object-fit сама держит пропорцию
 * картинки, отдельно её задавать незачем и нечем управлять честно. */
function ResizeHandle({ onPointerDown }: { onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void }) {
  return (
    <div
      className="files-resize-handle"
      onPointerDown={onPointerDown}
      title="Изменить размер"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" width="10" height="10">
        <path d="M20 4L4 20M20 12L12 20" />
      </svg>
    </div>
  )
}

/** Свободный «стол» для десктопа: фото не обрезаются (высота карточки
 * идёт от собственных пропорций картинки, не от фиксированного бокса) и
 * лежат там, куда их перетащили. Позиция — проценты от размера стола, не
 * пиксели, чтобы расстановка не разъезжалась на другой ширине экрана.
 * Двигать можно только в editMode — общий переключатель «Редактировать/
 * Готово» в шапке (решение пользователя: один тумблер на всё, а не замок
 * на каждом фото). */
export function PhotoBoard({
  photos,
  editMode,
  onMove,
  onDelete,
  onResize,
}: {
  photos: PhotoMeta[]
  editMode: boolean
  onMove: (id: string, x: number, y: number) => void
  onDelete: (id: string) => void
  onResize: (id: string, width: number) => void
}) {
  const boardRef = useRef<HTMLDivElement>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const dragOffset = useRef({ dx: 0, dy: 0 })
  const [livePos, setLivePos] = useState<Record<string, { x: number; y: number }>>({})

  const [resizeId, setResizeId] = useState<string | null>(null)
  const resizeStart = useRef({ startX: 0, startWidth: DEFAULT_PHOTO_WIDTH })
  const [liveWidth, setLiveWidth] = useState<Record<string, number>>({})

  const startDrag = useCallback(
    (e: React.PointerEvent<HTMLDivElement>, photo: PhotoMeta) => {
      if (!editMode) return
      e.preventDefault()
      // Карточка спозиционирована по ЦЕНТРУ (left/top% + translate(-50%,-50%)
      // в CSS), а не по левому верхнему углу — смещение курсора нужно
      // считать от центра, иначе позиция при переносе в проценты съезжает
      // на половину ширины/высоты карточки, и курсор на глаз оказывается
      // далеко внизу-справа от самой картинки (баг, пойманный вживую
      // 16 сентября 2026 на портретных фото — там половина высоты заметна
      // особенно сильно).
      const cardRect = e.currentTarget.getBoundingClientRect()
      const centerX = cardRect.left + cardRect.width / 2
      const centerY = cardRect.top + cardRect.height / 2
      dragOffset.current = { dx: e.clientX - centerX, dy: e.clientY - centerY }
      setDragId(photo.id)
      e.currentTarget.setPointerCapture(e.pointerId)
    },
    [editMode],
  )

  const startResize = useCallback(
    (e: React.PointerEvent<HTMLDivElement>, photo: PhotoMeta) => {
      if (!editMode) return
      e.preventDefault()
      e.stopPropagation() // не открывать заодно move-drag на карточке под ручкой
      resizeStart.current = { startX: e.clientX, startWidth: photo.width }
      setResizeId(photo.id)
      e.currentTarget.setPointerCapture(e.pointerId)
    },
    [editMode],
  )

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (dragId) {
        const board = boardRef.current
        if (!board) return
        const rect = board.getBoundingClientRect()
        const xPx = e.clientX - rect.left - dragOffset.current.dx
        const yPx = e.clientY - rect.top - dragOffset.current.dy
        const xPct = clamp((xPx / rect.width) * 100, 0, 100)
        const yPct = clamp((yPx / rect.height) * 100, 0, 100)
        setLivePos((prev) => ({ ...prev, [dragId]: { x: xPct, y: yPct } }))
      } else if (resizeId) {
        // Карточка растёт из своего центра (та же система координат, что
        // и позиция) — правый край уходит от центра на половину ширины,
        // поэтому чтобы он честно шёл за курсором, ширина растёт вдвое
        // быстрее сдвига курсора по горизонтали.
        const dx = e.clientX - resizeStart.current.startX
        const width = clamp(resizeStart.current.startWidth + dx * 2, MIN_PHOTO_WIDTH, MAX_PHOTO_WIDTH)
        setLiveWidth((prev) => ({ ...prev, [resizeId]: width }))
      }
    },
    [dragId, resizeId],
  )

  const endInteraction = useCallback(() => {
    if (dragId) {
      const pos = livePos[dragId]
      const id = dragId
      setDragId(null)
      if (pos) onMove(id, pos.x, pos.y)
    }
    if (resizeId) {
      const width = liveWidth[resizeId]
      const id = resizeId
      setResizeId(null)
      if (width != null) onResize(id, width)
    }
  }, [dragId, livePos, onMove, resizeId, liveWidth, onResize])

  return (
    <div
      className={`files-board${editMode ? ' is-editing' : ''}`}
      ref={boardRef}
      onPointerMove={onPointerMove}
      onPointerUp={endInteraction}
      onPointerCancel={endInteraction}
    >
      {photos.map((p) => {
        // livePos/liveWidth — только пока ЭТА карточка реально тащится —
        // после отпускания их записи не чистятся (не нужно: следующий
        // рендер снова берёт entry из map, но map держит значение вечно),
        // и если новое значение с сервера/от другого действия (кнопка
        // "вернуть размер") отличается от последнего перетащенного, экран
        // молча застревал бы на старом. Живой баг 16 сентября 2026: после
        // resize-перетаскивания кнопка "вернуть исходный размер" реально
        // сохраняла 170 на сервере, но карточка на экране оставалась
        // прежней ширины — потому что рендер продолжал читать
        // liveWidth[id] вместо свежего p.width.
        const pos = dragId === p.id ? livePos[p.id] ?? { x: p.pos_x, y: p.pos_y } : { x: p.pos_x, y: p.pos_y }
        const width = resizeId === p.id ? liveWidth[p.id] ?? p.width : p.width
        return (
          <div
            key={p.id}
            className={`files-card${dragId === p.id ? ' is-dragging' : ''}`}
            style={{ left: `${pos.x}%`, top: `${pos.y}%`, width: `${width}px` }}
            onPointerDown={(e) => startDrag(e, p)}
          >
            <img src={p.url} alt={p.filename} className="files-card-img" draggable={false} />
            <DeleteButton onDelete={() => onDelete(p.id)} />
            {editMode && (
              <>
                <ResetSizeButton onReset={() => onResize(p.id, DEFAULT_PHOTO_WIDTH)} />
                <ResizeHandle onPointerDown={(e) => startResize(e, p)} />
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Мобильная masonry-плитка: колонки CSS `columns`, не grid — высота
 * каждой карточки идёт от родной пропорции фото (портретные/альбомные не
 * обрезаются и не уравниваются под одну высоту), а не фиксированный
 * aspect-ratio 16:9, как было раньше. */
function MobilePhotoTile({ photo, onDelete }: { photo: PhotoMeta; onDelete: () => void }) {
  return (
    <div className="files-masonry-tile">
      <img src={photo.url} alt={photo.filename} className="files-masonry-img" />
      <DeleteButton onDelete={onDelete} />
    </div>
  )
}

export function PhotoGrid({
  photos,
  loading,
  uploading,
  error,
  onDelete,
}: {
  photos: PhotoMeta[] | null
  loading: boolean
  uploading: boolean
  error: string | null
  onDelete: (id: string) => void
}) {
  if (loading) {
    return <div className="files-empty">Загружаем…</div>
  }

  const hasPhotos = (photos?.length ?? 0) > 0

  return (
    <div className="files-wrap">
      {error && <div className="files-error">{error}</div>}
      {uploading && <div className="files-uploading">Загружаем фото…</div>}
      {hasPhotos ? (
        <div className="files-masonry">
          {photos!.map((p) => (
            <MobilePhotoTile key={p.id} photo={p} onDelete={() => onDelete(p.id)} />
          ))}
        </div>
      ) : (
        <div className="files-empty">
          <span>Пока нет загруженных фото</span>
        </div>
      )}
    </div>
  )
}

export function DesktopBoardArea({
  photos,
  loading,
  uploading,
  error,
  editMode,
  onUpload,
  onDelete,
  onMove,
  onResize,
}: {
  photos: PhotoMeta[] | null
  loading: boolean
  uploading: boolean
  error: string | null
  editMode: boolean
  onUpload: (file: File) => void
  onDelete: (id: string) => void
  onMove: (id: string, x: number, y: number) => void
  onResize: (id: string, width: number) => void
}) {
  if (loading) {
    return <div className="files-empty">Загружаем…</div>
  }

  const hasPhotos = (photos?.length ?? 0) > 0

  return (
    <div className="files-wrap">
      {error && <div className="files-error">{error}</div>}
      {uploading && <div className="files-uploading">Загружаем фото…</div>}
      {hasPhotos ? (
        <PhotoBoard photos={photos!} editMode={editMode} onMove={onMove} onDelete={onDelete} onResize={onResize} />
      ) : (
        <div className="files-empty">
          <span>Пока нет загруженных фото</span>
          <AddTile onPick={onUpload} large />
        </div>
      )}
    </div>
  )
}

export { AddButton }
