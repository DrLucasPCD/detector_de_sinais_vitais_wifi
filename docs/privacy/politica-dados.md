# Política de dados do protótipo

| Classe | Conteúdo | Retenção padrão | Egresso |
|---|---|---:|---|
| P0 | CSI I/Q bruto | zero; somente buffer volátil | nenhum |
| P1 | features e qualidade | zero nesta versão | API local |
| P2 | presença e movimento | zero nesta versão | API/WS local |
| P3 | respiração e frequência cardíaca | zero e opt-in futuro | finalidade explícita |
| P4 | identidade/biometria | proibido | nenhum |

O dashboard faz bind em loopback por padrão. Acesso por terceiros exige
consentimento, sinalização, finalidade e prazo de retenção. A ausência de câmera
não elimina a necessidade de informar a medição.

