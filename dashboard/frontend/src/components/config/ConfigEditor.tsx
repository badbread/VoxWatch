/**
 * ConfigEditor — main config page with vertical tab navigation and save bar.
 *
 * Loads the current config via React Query, tracks local edits in component
 * state, runs client-side validation on every change, and commits via the
 * save mutation. The ConfigSaveBar slides up from the bottom when the form
 * is dirty.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Server,
  Radio,
  Clock,
  Brain,
  Layers,
  // Volume2 removed — Audio Output section removed
  // Mic and FileText removed — TTS/Logging sections restructured
  Theater,
  Headphones,
  MapPin,
} from 'lucide-react';
import { cn } from '@/utils/cn';
import { Card } from '@/components/common/Card';
import { PageSpinner } from '@/components/common/LoadingSpinner';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { ConfigSaveBar } from './ConfigSaveBar';
import { FrigateConfigForm } from './FrigateConfigForm';
import { Go2rtcConfigForm } from './Go2rtcConfigForm';
// CamerasConfigForm removed — camera config now lives on the Cameras page (/cameras)
import { ConditionsConfigForm } from './ConditionsConfigForm';
import { ZonesConfigForm } from './ZonesConfigForm';
import { AiConfigForm } from './AiConfigForm';
import { StagesConfigForm } from './StagesConfigForm';
import { TtsConfigForm } from './TtsConfigForm';
// AudioConfigForm removed — codec settings are per-camera now
// LoggingConfigForm removed — logging tab removed from config editor
import { PersonaConfigForm } from './PersonaConfigForm';
import { useConfigQuery, useConfigMutation } from '@/hooks/useConfig';
import { validateConfig } from '@/utils/validators';
import { inputCls, Field } from '@/components/common/FormField';
import type { VoxWatchConfig } from '@/types/config';

interface TabDef {
  id: string;
  label: string;
  icon: React.ElementType;
  section: keyof VoxWatchConfig | 'stages' | 'audio_combined' | 'response_mode';
}

// Note: the Cameras tab has been removed — camera management now lives on the
// Cameras page (/cameras) where users can add, edit, and remove cameras inline.
const TABS: TabDef[] = [
  { id: 'response_mode', label: 'Personality', icon: Theater, section: 'response_mode' },
  { id: 'tts', label: 'TTS', icon: Headphones, section: 'response_mode' },
  { id: 'detection', label: 'Schedule', icon: Clock, section: 'conditions' },
  { id: 'zones', label: 'Camera Zones', icon: MapPin, section: 'conditions' },
  { id: 'pipeline', label: 'Pipeline', icon: Layers, section: 'stages' },
  { id: 'ai', label: 'AI Provider', icon: Brain, section: 'ai' },
  { id: 'services', label: 'Connections', icon: Server, section: 'frigate' },
];

/**
 * Full configuration editor with tabbed sections and sticky save bar.
 */
export function ConfigEditor() {
  const { data: remoteConfig, isLoading } = useConfigQuery();
  const saveMutation = useConfigMutation();

  const [localConfig, setLocalConfig] = useState<VoxWatchConfig | null>(null);

  // Support ?tab={id} query param for deep linking to a specific section
  const searchParams = new URLSearchParams(window.location.search);
  const initialTab = TABS.find((t) => t.id === searchParams.get('tab'))?.id ?? TABS[0]!.id;
  const [activeTab, setActiveTab] = useState(initialTab);
  const [isDirty, setIsDirty] = useState(false);

  // Seed local state from the fetched config
  useEffect(() => {
    if (remoteConfig && !isDirty) {
      setLocalConfig(remoteConfig);
    }
  }, [remoteConfig, isDirty]);

  const handleChange = useCallback(
    (patch: Partial<VoxWatchConfig>) => {
      setLocalConfig((prev) => {
        if (!prev) return prev;
        return { ...prev, ...patch };
      });
      setIsDirty(true);
    },
    [],
  );

  const validationResult = localConfig
    ? validateConfig(localConfig)
    : { valid: false, errors: [] };

  const handleSave = () => {
    if (!localConfig) return;
    saveMutation.mutate(localConfig, {
      onSuccess: () => setIsDirty(false),
    });
  };

  const handleDiscard = () => {
    if (remoteConfig) {
      setLocalConfig(remoteConfig);
      setIsDirty(false);
    }
  };

  if (isLoading || !localConfig) {
    return <PageSpinner />;
  }

  const activeTabDef = TABS.find((t) => t.id === activeTab);

  return (
    <div className="flex min-h-0 flex-col gap-4">
      <div className="flex gap-4">
        {/* Vertical tab list */}
        <nav
          aria-label="Configuration sections"
          className="hidden w-40 flex-shrink-0 sm:block lg:w-48"
        >
          <ul className="space-y-0.5">
            {TABS.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <button
                  onClick={() => setActiveTab(id)}
                  className={cn(
                    'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                    activeTab === id
                      ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-400'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100',
                  )}
                  aria-current={activeTab === id ? 'page' : undefined}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        {/* Mobile tab selector */}
        <div className="sm:hidden">
          <select
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
          >
            {TABS.map(({ id, label }) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>

        {/* Form panel */}
        <div className="min-w-0 flex-1">
          <ErrorBoundary>
            <Card title={activeTabDef?.label}>
              {/* Services: Frigate + go2rtc */}
              {activeTab === 'services' && (
                <div className="space-y-6">
                  <div>
                    <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200">
                      <Server className="h-4 w-4 text-blue-500" /> Frigate NVR
                    </h4>
                    <FrigateConfigForm
                      value={localConfig.frigate}
                      onChange={(frigate) => handleChange({ frigate })}
                      errors={validationResult.errors}
                    />
                  </div>
                  <hr className="border-gray-200 dark:border-gray-700" />
                  <div>
                    <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200">
                      <Radio className="h-4 w-4 text-purple-500" /> go2rtc
                    </h4>
                    <Go2rtcConfigForm
                      value={localConfig.go2rtc}
                      onChange={(go2rtc) => handleChange({ go2rtc })}
                      errors={validationResult.errors}
                    />
                  </div>
                  <hr className="border-gray-200 dark:border-gray-700" />
                  <div>
                    <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                      <Radio className="h-4 w-4 text-green-500" /> MQTT Publishing
                    </h4>
                    <p className="mb-3 text-sm text-gray-600 dark:text-gray-400">
                      Publish VoxWatch events to MQTT for Home Assistant automations.
                    </p>
                    <div className="space-y-3">
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={localConfig.mqtt_publish?.enabled ?? true}
                          onChange={(e) => handleChange({
                            mqtt_publish: {
                              ...localConfig.mqtt_publish,
                              enabled: e.target.checked,
                            },
                          })}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                        Enable MQTT event publishing
                      </label>
                      {(localConfig.mqtt_publish?.enabled ?? true) && (
                        <div className="ml-6 space-y-3">
                          <Field label="Topic Prefix">
                            <input
                              type="text"
                              value={localConfig.mqtt_publish?.topic_prefix ?? 'voxwatch'}
                              onChange={(e) => handleChange({
                                mqtt_publish: {
                                  ...localConfig.mqtt_publish,
                                  topic_prefix: e.target.value,
                                },
                              })}
                              placeholder="voxwatch"
                              className={inputCls(false)}
                            />
                          </Field>
                          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                            <input
                              type="checkbox"
                              checked={localConfig.mqtt_publish?.include_ai_analysis ?? true}
                              onChange={(e) => handleChange({
                                mqtt_publish: {
                                  ...localConfig.mqtt_publish,
                                  include_ai_analysis: e.target.checked,
                                },
                              })}
                              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            />
                            Include AI analysis in stage events
                          </label>
                          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                            <input
                              type="checkbox"
                              checked={localConfig.mqtt_publish?.include_snapshot_url ?? true}
                              onChange={(e) => handleChange({
                                mqtt_publish: {
                                  ...localConfig.mqtt_publish,
                                  include_snapshot_url: e.target.checked,
                                },
                              })}
                              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            />
                            Include Frigate snapshot URL in events
                          </label>
                          <p className="text-xs text-gray-400 dark:text-gray-500">
                            Events publish to: {localConfig.mqtt_publish?.topic_prefix ?? 'voxwatch'}/events/*
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
              {activeTab === 'detection' && (
                <ConditionsConfigForm
                  value={localConfig.conditions}
                  cameras={localConfig.cameras}
                  onChange={(conditions) => handleChange({ conditions })}
                  onCamerasChange={(cameras) => handleChange({ cameras })}
                  errors={validationResult.errors}
                />
              )}
              {activeTab === 'zones' && (
                <ZonesConfigForm
                  zones={localConfig.zones}
                  cameras={localConfig.cameras}
                  onChange={(zones) => {
                    if (zones) {
                      handleChange({ zones });
                    } else {
                      // Clear zones — spread without the key
                      const { zones: _, ...rest } = localConfig;
                      handleChange(rest as Partial<VoxWatchConfig>);
                    }
                  }}
                />
              )}
              {activeTab === 'ai' && (
                <AiConfigForm
                  value={localConfig.ai}
                  onChange={(ai) => handleChange({ ai })}
                  errors={validationResult.errors}
                />
              )}
              {/* Pipeline: Stages + TTS + Audio + Messages */}
              {activeTab === 'pipeline' && (
                <div className="space-y-6">
                  <StagesConfigForm
                    stage2={localConfig.stage2}
                    stage3={localConfig.stage3}
                    messages={localConfig.messages}
                    pipeline={localConfig.pipeline}
                    onStage2Change={(stage2) => handleChange({ stage2 })}
                    onStage3Change={(stage3) => handleChange({ stage3 })}
                    onMessagesChange={(messages) => handleChange({ messages })}
                    onPipelineChange={(pipeline) => handleChange({ pipeline })}
                    errors={validationResult.errors}
                  />
                  {/* Audio Output removed — codec/sample_rate/channels are per-camera settings */}
                </div>
              )}
              {activeTab === 'response_mode' && (
                <PersonaConfigForm
                  value={
                    localConfig.response_mode ??
                    localConfig.persona ?? { name: 'standard', custom_prompt: '' }
                  }
                  onChange={(response_mode) => handleChange({ response_mode })}
                  errors={validationResult.errors}
                  ttsConfig={localConfig.tts}
                />
              )}
              {activeTab === 'tts' && (
                <TtsConfigForm
                  value={localConfig.tts}
                  onChange={(tts) => handleChange({ tts })}
                  errors={validationResult.errors}
                  activePersona={
                    localConfig.response_mode?.name ??
                    localConfig.persona?.name ??
                    'standard'
                  }
                />
              )}
            </Card>
          </ErrorBoundary>
        </div>
      </div>

      {/* Sticky save bar */}
      <ConfigSaveBar
        isDirty={isDirty}
        isSaving={saveMutation.isPending}
        errors={validationResult.errors}
        originalConfig={remoteConfig ?? null}
        currentConfig={localConfig}
        onSave={handleSave}
        onDiscard={handleDiscard}
      />
    </div>
  );
}
