import { useEffect, useMemo, useRef } from 'react'
import { CircleMarker, MapContainer, Marker, TileLayer, Tooltip, ZoomControl, useMap } from 'react-leaflet'
import L from 'leaflet'
import { COLORS, TRIAGE, effectivePriority, labelFor } from './lib'

const HOUSTON = [29.76, -95.4]

const pulseIcon = L.divIcon({ className: 'pulse-pin', iconSize: [34, 34] })
const dragIcon = L.divIcon({ className: 'drag-pin', iconSize: [26, 26], iconAnchor: [13, 26] })

function FlyTo({ target }) {
  const map = useMap()
  useEffect(() => {
    if (target) map.flyTo(target, Math.max(map.getZoom(), 13), { duration: 0.6 })
  }, [target?.[0], target?.[1]])
  return null
}

function pinRadius(c, selected) {
  if (c.status === 'rescued' || c.status === 'closed') return 4
  const r = 5 + Math.min(6, c.people_count || 1)
  return selected ? r + 3 : r
}

function pinStyle(c, selected, now) {
  const triage = TRIAGE[labelFor(effectivePriority(c, now))]
  if (c.status === 'rescued' || c.status === 'closed') {
    return { color: '#fff', weight: 1, fillColor: COLORS.rescued, fillOpacity: 0.6 }
  }
  if (c.status === 'assigned') {
    return { color: selected ? COLORS.water : COLORS.ink, weight: 3, fillColor: '#fff', fillOpacity: 1 }
  }
  return {
    color: selected ? COLORS.ink : '#fff',
    weight: selected ? 3 : 2,
    dashArray: c.location_confidence === 'approximate' ? '3 3' : undefined,
    fillColor: triage.color,
    fillOpacity: 0.95,
  }
}

export default function MapView({ cases, selectedId, onSelect, draft, onDraftMove, now }) {
  const located = useMemo(() => cases.filter((c) => c.lat != null && c.lng != null), [cases])
  const selected = cases.find((c) => c.id === selectedId)
  const target = selected && selected.lat != null ? [selected.lat, selected.lng] : null
  const markerRef = useRef(null)

  // draw lowest priority first so urgent pins sit on top
  const ordered = useMemo(
    () => [...located].sort((a, b) => effectivePriority(a, now) - effectivePriority(b, now)),
    [located, now],
  )

  return (
    <MapContainer center={HOUSTON} zoom={10} className="map" preferCanvas zoomControl={false}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
      />
      <ZoomControl position="bottomright" />
      <FlyTo target={target} />
      {ordered.map((c) => (
        <CircleMarker
          key={c.id}
          center={[c.lat, c.lng]}
          radius={pinRadius(c, c.id === selectedId)}
          pathOptions={pinStyle(c, c.id === selectedId, now)}
          eventHandlers={{ click: () => onSelect(c.id) }}
        >
          <Tooltip direction="top" offset={[0, -6]}>
            <strong>{c.case_number}</strong> {c.address || c.landmark}
            <br />
            {c.people_count ? `${c.people_count} people, ` : ''}
            {c.status === 'assigned' ? `${c.unit} assigned` : TRIAGE[labelFor(effectivePriority(c, now))].word}
          </Tooltip>
        </CircleMarker>
      ))}
      {located
        .filter((c) => c.life_threatening && c.status === 'open')
        .map((c) => (
          <Marker key={`pulse-${c.id}`} position={[c.lat, c.lng]} icon={pulseIcon} interactive={false} />
        ))}
      {draft && (
        <Marker
          ref={markerRef}
          position={draft}
          icon={dragIcon}
          draggable
          eventHandlers={{
            dragend: () => {
              const p = markerRef.current?.getLatLng()
              if (p) onDraftMove([p.lat, p.lng])
            },
          }}
        />
      )}
    </MapContainer>
  )
}
