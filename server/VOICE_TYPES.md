# Voice Types (Clone vs Custom)

This server supports two distinct voice types:

1. **Clone voices**
   - Stored in `server/voices/<name>/prompt.pkl`
   - Generated via the Base model (`generate_voice_clone`)
   - Example: `noel`, `lynch`, `george_carlin`

2. **Custom voices**
   - Built-in speakers from the CustomVoice model config
   - Generated via `generate_custom_voice`
   - Example: `aiden`, `ryan`

Endpoints:
```
GET /voices          # combined list (clone + custom)
GET /voices/clones   # clone voices only
GET /voices/custom   # custom voices only
```
