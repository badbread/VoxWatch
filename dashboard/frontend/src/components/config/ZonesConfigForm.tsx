/**
 * ZonesConfigForm — camera zone editor.
 *
 * Lets users group cameras by physical area so that:
 *  - One detection triggers one speaker (the zone's designated speaker)
 *  - All cameras in a zone share a single cooldown timer
 *  - (Future) Snapshots from all zone cameras are fused for richer AI descriptions
 */

import { useState } from 'react';
import { Plus, Trash2, MapPin } from 'lucide-react';
import { cn } from '@/utils/cn';
import { inputCls, Field } from '@/components/common/FormField';
import type { ZoneConfig, CameraConfig } from '@/types/config';

export interface ZonesConfigFormProps {
  /** Current zones config (may be undefined/null if no zones configured). */
  zones: Record<string, ZoneConfig> | undefined;
  /** All configured cameras — used to populate camera selection dropdowns. */
  cameras: Record<string, CameraConfig>;
  /** Called when zones change. Pass undefined to clear all zones. */
  onChange: (zones: Record<string, ZoneConfig> | undefined) => void;
}

/**
 * Camera zone editor — add, edit, and remove zones.
 */
export function ZonesConfigForm({ zones, cameras, onChange }: ZonesConfigFormProps) {
  const [newZoneName, setNewZoneName] = useState('');

  const zoneEntries = Object.entries(zones ?? {});
  const allCameraNames = Object.keys(cameras);

  // Cameras already assigned to a zone (can't be in multiple zones)
  const assignedCameras = new Set(
    zoneEntries.flatMap(([, z]) => z.cameras),
  );

  // Available cameras for a specific zone (its own cameras + unassigned)
  function availableCameras(currentZoneCameras: string[]): string[] {
    const currentSet = new Set(currentZoneCameras);
    return allCameraNames.filter(
      (name) => currentSet.has(name) || !assignedCameras.has(name),
    );
  }

  function updateZone(name: string, patch: Partial<ZoneConfig>) {
    const current = zones ?? {};
    const existing = current[name] ?? { cameras: [], speaker: '' };
    onChange({ ...current, [name]: { ...existing, ...patch } });
  }

  function removeZone(name: string) {
    const current = { ...(zones ?? {}) };
    delete current[name];
    onChange(Object.keys(current).length > 0 ? current : undefined);
  }

  function addZone() {
    const name = newZoneName.trim().toLowerCase().replace(/\s+/g, '_');
    if (!name || (zones ?? {})[name]) return;
    const current = zones ?? {};
    onChange({ ...current, [name]: { cameras: [], speaker: '' } });
    setNewZoneName('');
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500 dark:text-gray-400">
        Group cameras by physical area. All cameras in a zone share a single cooldown
        and route audio to one designated speaker.
      </p>

      {zoneEntries.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 px-6 py-8 text-center">
          <MapPin className="mx-auto h-8 w-8 text-gray-400 dark:text-gray-600" />
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            No zones configured. Cameras operate independently.
          </p>
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-600">
            Create a zone to group cameras that cover the same area.
          </p>
        </div>
      )}

      {/* Zone cards */}
      {zoneEntries.map(([zoneName, zone]) => {
        const available = availableCameras(zone.cameras);
        return (
          <div
            key={zoneName}
            className="rounded-xl border border-gray-200 dark:border-gray-700/50 bg-gray-50 dark:bg-gray-800/30 p-4 space-y-3"
          >
            {/* Zone header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MapPin className="h-4 w-4 text-blue-500" />
                <h4 className="text-sm font-bold text-gray-900 dark:text-gray-100">
                  {zoneName}
                </h4>
                <span className="text-xs text-gray-400">
                  {zone.cameras.length} camera{zone.cameras.length !== 1 ? 's' : ''}
                </span>
              </div>
              <button
                type="button"
                onClick={() => removeZone(zoneName)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 transition-colors"
                aria-label={`Remove zone ${zoneName}`}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>

            {/* Camera selection */}
            <Field label="Cameras in this zone">
              <div className="flex flex-wrap gap-2">
                {zone.cameras.map((cam) => (
                  <span
                    key={cam}
                    className="inline-flex items-center gap-1 rounded-full bg-blue-100 dark:bg-blue-900/40 px-2.5 py-1 text-xs font-medium text-blue-700 dark:text-blue-300"
                  >
                    {cam}
                    <button
                      type="button"
                      onClick={() => {
                        const updated = zone.cameras.filter((c) => c !== cam);
                        const patch: Partial<ZoneConfig> = { cameras: updated };
                        // If speaker was removed, clear it
                        if (zone.speaker === cam) patch.speaker = updated[0] ?? '';
                        updateZone(zoneName, patch);
                      }}
                      className="ml-0.5 text-blue-400 hover:text-blue-600"
                      aria-label={`Remove ${cam} from zone`}
                    >
                      &times;
                    </button>
                  </span>
                ))}
                {available.filter((c) => !zone.cameras.includes(c)).length > 0 && (
                  <select
                    value=""
                    onChange={(e) => {
                      if (!e.target.value) return;
                      updateZone(zoneName, {
                        cameras: [...zone.cameras, e.target.value],
                        // Auto-set speaker if first camera added
                        ...(zone.cameras.length === 0 ? { speaker: e.target.value } : {}),
                      });
                    }}
                    className={cn(inputCls(false), 'w-auto text-xs')}
                  >
                    <option value="">+ Add camera</option>
                    {available
                      .filter((c) => !zone.cameras.includes(c))
                      .map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                  </select>
                )}
              </div>
            </Field>

            {/* Speaker selection */}
            {zone.cameras.length > 0 && (
              <Field
                label="Speaker"
                hint="Which camera's speaker plays audio when any camera in this zone detects someone."
              >
                <select
                  value={zone.speaker}
                  onChange={(e) => updateZone(zoneName, { speaker: e.target.value })}
                  className={inputCls(false)}
                >
                  <option value="">Select speaker...</option>
                  {zone.cameras.map((cam) => (
                    <option key={cam} value={cam}>{cam}</option>
                  ))}
                </select>
              </Field>
            )}

            {/* Cooldown override */}
            <Field
              label="Zone Cooldown (seconds)"
              hint="Leave empty to use the global cooldown."
            >
              <input
                type="number"
                min={10}
                max={600}
                step={10}
                value={zone.cooldown_seconds ?? ''}
                onChange={(e) => {
                  const val = e.target.value;
                  if (val) {
                    updateZone(zoneName, { cooldown_seconds: Number(val) });
                  } else {
                    // Clear the override — use spread to omit the key
                    const current = (zones ?? {})[zoneName];
                    if (current) {
                      const { cooldown_seconds: _, ...rest } = current;
                      const updated = { ...(zones ?? {}), [zoneName]: rest as ZoneConfig };
                      onChange(updated);
                    }
                  }
                }}
                placeholder="Use global"
                className={inputCls(false)}
              />
            </Field>
          </div>
        );
      })}

      {/* Add new zone */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={newZoneName}
          onChange={(e) => setNewZoneName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addZone(); } }}
          placeholder="Zone name (e.g., front, back, side)"
          className={cn(inputCls(false), 'flex-1')}
        />
        <button
          type="button"
          onClick={addZone}
          disabled={!newZoneName.trim()}
          className={cn(
            'flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
            'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          <Plus className="h-3.5 w-3.5" />
          Add Zone
        </button>
      </div>
    </div>
  );
}
