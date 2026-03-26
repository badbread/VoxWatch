# Home Assistant Integration

VoxWatch publishes MQTT events at every stage of a detection so your entire
smart home can respond to intruders automatically.  No direct Home Assistant
API integration needed -- just MQTT messages with structured JSON payloads.

## How It Works

1. VoxWatch detects a person via Frigate
2. VoxWatch publishes events to MQTT as it responds
3. Home Assistant triggers automations based on those events
4. Your lights, locks, speakers, notifications all react

## MQTT Topics

All topics are under a configurable prefix (default `voxwatch/`):

| Topic | When | Use For |
|-------|------|---------|
| `voxwatch/events/detection` | Person detected | Lights on, notifications |
| `voxwatch/events/stage` | Stage 1/2/3 fires | Escalating response |
| `voxwatch/events/ended` | Detection over | Restore normal state |
| `voxwatch/events/error` | Something failed | Alert on failures |
| `voxwatch/status` | Startup/shutdown | Online/offline sensor |

## Event Payloads

### detection (person detected)

```json
{
  "event": "detection_started",
  "event_id": "vw_1711338420_driveway",
  "timestamp": "2026-03-25T02:47:00.000000Z",
  "camera": "driveway",
  "frigate_event_id": "abc123",
  "mode": "police_dispatch",
  "snapshot_url": "http://frigate:5000/api/events/abc123/snapshot.jpg"
}
```

### stage (each stage fires)

```json
{
  "event": "stage_triggered",
  "event_id": "vw_1711338420_driveway",
  "timestamp": "2026-03-25T02:47:05.000000Z",
  "camera": "driveway",
  "stage": 2,
  "total_stages": 3,
  "mode": "police_dispatch",
  "audio_pushed": true,
  "ai_analysis": {
    "description": "dark hoodie and gray pants, approaching side gate"
  },
  "person_still_present": true,
  "frigate_event_id": "abc123"
}
```

### ended (detection concluded)

```json
{
  "event": "detection_ended",
  "event_id": "vw_1711338420_driveway",
  "timestamp": "2026-03-25T02:47:35.000000Z",
  "camera": "driveway",
  "reason": "all_stages_completed",
  "stages_completed": 2,
  "total_duration_seconds": 30.0,
  "mode": "police_dispatch",
  "frigate_event_id": "abc123"
}
```

Possible `reason` values: `person_left`, `all_stages_completed`, `error`

### error

```json
{
  "event": "error",
  "event_id": "vw_1711338420_driveway",
  "camera": "driveway",
  "stage": 2,
  "error_type": "tts_failure",
  "error_message": "ElevenLabs timeout, fell back to piper",
  "fallback_used": true
}
```

## Configuration

In the VoxWatch dashboard under **Connections**, enable MQTT Publishing:

```yaml
mqtt_publish:
  enabled: true
  topic_prefix: "voxwatch"
  include_ai_analysis: true
  include_snapshot_url: true
```

## VoxWatch Online/Offline Sensor

Add to your HA `configuration.yaml`:

```yaml
mqtt:
  binary_sensor:
    - name: "VoxWatch Status"
      state_topic: "voxwatch/status"
      payload_on: "online"
      payload_off: "offline"
      device_class: running
```

## Example Automations

### All Exterior Lights to 100% on Detection

```yaml
automation:
  - alias: "VoxWatch - All lights on detection"
    trigger:
      - platform: mqtt
        topic: "voxwatch/events/detection"
    action:
      - service: light.turn_on
        target:
          entity_id:
            - light.front_porch
            - light.driveway
            - light.backyard
            - light.side_gate
        data:
          brightness: 255
```

### Phone Notification with AI Description

```yaml
automation:
  - alias: "VoxWatch - Phone alert with description"
    trigger:
      - platform: mqtt
        topic: "voxwatch/events/stage"
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.stage == 2 }}"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "VoxWatch Alert - {{ trigger.payload_json.camera }}"
          message: >
            Person detected on {{ trigger.payload_json.camera }}.
            Mode: {{ trigger.payload_json.mode }}.
          data:
            image: "{{ trigger.payload_json.snapshot_url }}"
            tag: "{{ trigger.payload_json.event_id }}"
```

### Red/Blue Police Lights on Stage 2

```yaml
automation:
  - alias: "VoxWatch - Police lights on Stage 2"
    trigger:
      - platform: mqtt
        topic: "voxwatch/events/stage"
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.stage == 2 }}"
      - condition: template
        value_template: "{{ trigger.payload_json.mode == 'police_dispatch' }}"
    action:
      - repeat:
          count: 10
          sequence:
            - service: light.turn_on
              target:
                entity_id: light.eave_lights
              data:
                color_name: red
                brightness: 255
            - delay: 0.5
            - service: light.turn_on
              target:
                entity_id: light.eave_lights
              data:
                color_name: blue
                brightness: 255
            - delay: 0.5
```

### Lock Doors and Close Garage on Stage 2

```yaml
automation:
  - alias: "VoxWatch - Lock up on Stage 2"
    trigger:
      - platform: mqtt
        topic: "voxwatch/events/stage"
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.stage >= 2 }}"
    action:
      - service: lock.lock
        target:
          entity_id:
            - lock.front_door
            - lock.back_door
      - service: cover.close_cover
        target:
          entity_id: cover.garage_door
```

### Interior Lights to Simulate Occupancy

```yaml
automation:
  - alias: "VoxWatch - Interior lights for occupancy"
    trigger:
      - platform: mqtt
        topic: "voxwatch/events/stage"
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.stage == 1 }}"
      - condition: state
        entity_id: input_boolean.away_mode
        state: "on"
    action:
      - service: light.turn_on
        target:
          entity_id: light.living_room
        data:
          brightness: 200
      - delay: "00:00:03"
      - service: light.turn_on
        target:
          entity_id: light.master_bedroom
        data:
          brightness: 100
```

### Restore Lights After Detection Ends

```yaml
automation:
  - alias: "VoxWatch - Restore lights after event"
    trigger:
      - platform: mqtt
        topic: "voxwatch/events/ended"
    action:
      - delay: "00:02:00"
      - service: scene.turn_on
        target:
          entity_id: scene.nighttime_lighting
```

### Announce on Alexa / Google Home

```yaml
automation:
  - alias: "VoxWatch - Dispatch on Alexa"
    trigger:
      - platform: mqtt
        topic: "voxwatch/events/stage"
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.stage == 2 }}"
    action:
      - service: notify.alexa_media_living_room
        data:
          message: >
            Security alert. Person detected on {{ trigger.payload_json.camera }}.
            Authorities have been contacted.
          data:
            type: tts
```
