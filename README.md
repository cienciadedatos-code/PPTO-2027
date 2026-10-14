# GASTOS-MODEL

---

Automatización completa del pipeline de gastos (CEN, IPL, PRE), con generación incremental de GASTOS_master, backup automático y actualización compatible con Power BI Cloud.
Repo clonado en WindowsC: -> Repos
SharePoint debe estar local en explorador de archivos y conectado a la nube

---

## Descripción
Este proyecto contiene un pipeline en Python que:
* Lee la carpeta local de SharePoint: Reportes de PowerBI-> Documentos -> Gastos_SP
* Lee los archivos mensuales de gastos (CEN, IPL, PRE), Gastos_SP-> raw_gastos (aqui se ponen los nuevos archivos cada mes)
* Reconstruye la cuenta mayor por grupo.
* Unifica todas las empresas en una sola tabla consolidada.
* Calcula Empresa y Cuenta global usando un catálogo que esta en Gastos_SP-> consulta_gastos
* Elimina contrapartidas que inician en “301”.
* Combina histórico + registros nuevos.
* Reescribe el GASTOS_master que esta en Gastos_SP-> outputs_gastos.
* Actualiza automáticamente el archivo GASTOS_master.xlsx en SharePoint local y nube.
* Genera un backup mensual.
* Hay que darle refresh en PowerBI, el Dashboard lee el GASTOS_master.xlsx de SharePoint en Nube


(Más info detallada en el MTO)

---

## Dependencias

---
## Seguridad

No se suben los datos a GitHub por eso se leen en sharepoint los exceles de consulta y localmente. 

Las rutas se controlan desde settings.json para facilitar migración.



