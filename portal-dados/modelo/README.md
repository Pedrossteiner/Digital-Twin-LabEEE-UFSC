# Modelo 3D do Gêmeo Digital

`Labeee_gemeo.ifc` é o modelo BIM do LabEEE/UFSC (IFC4), preparado para o Gêmeo Digital: cada objeto que tem sensor recebeu o nome que o liga aos dados. Na demo ele aparece com os dados simulados.

| Objeto no IFC | Nome (atributo `Name`) | Ligado a |
|---|---|---|
| `IfcFurniture` (cadeira de cada mesa) | `Mesa 11` … `Mesa 64` | presença (PC ligado) |
| `IfcWindow` (folha que abre) | `1A`, `2B`, … | sensor de janela |
| `IfcDoor` | `PLB`, `PAM`, `PR1`, … | sensor de porta |
| `IfcSensor` | número de série do HOBO | temperatura, umidade, CO₂ |
| `IfcUnitaryEquipment` | `Daikin 1-04`, … | ar-condicionado |
| `IfcSpace` | nome da sala | (reservado) |

No build, `cozinhar_modelo.mjs` transforma o IFC numa versão leve (`Labeee_gemeo.bin.gz`): simplifica as peças com detalhe demais e junta as peças por material. Para usar outro modelo, substitua o arquivo mantendo essa convenção de nomes e refaça o build (`docker compose up -d --build`).
