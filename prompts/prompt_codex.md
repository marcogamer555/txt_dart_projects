No optimices por la solución más rápida, sino por la más limpia, mantenible y bien separada por capas. Nunca metas lógica de BLoC ni lógica compleja en las Pages.

Arquitectura y capas (Clean Architecture)
Respeta SIEMPRE esta estructura y dirección de dependencias dentro de :

/core

/features

- `presentation` → depende de → `domain` → depende de → `data`.
- `domain`:
  - Define `entities`, interfaces de `repositories` y `usecases`.
- `data`:
  - Implementa los `repositories` del domain.
  - Define `datasources` y `models`.
  - Mapea `models ↔ entities`.
- `presentation`:
  - `blocs`: toda la lógica de estado.
  - `pages`: orquestan, instancian widgets y conectan BLoCs (por inyección/proveedores).
  - `widgets`: componentes reutilizables de UI.

Reglas de responsabilidades
- Nada de lógica de BLoC dentro de las Pages.
- Nada de lógica de UI dentro de los BLoCs.
- Las Pages solo:
  - Arman la estructura de pantalla.
  - Instancian widgets.
  - Conectan BLoCs y providers.
- Usa `app_theme.dart` para estilos y colores, no hardcodees estilos que deban centralizarse.

Organización de widgets y reutilización
- Antes de crear nuevos widgets, revisa si existe algo similar en `/core` o en los widgets actuales de la feature.
- Identifica código de UI redundante o muy similar y extrae widgets reutilizables a `presentation/widgets` (o a la carpeta de widgets de la feature, según convenga).
- Evita construir toda la UI directamente en la Page: crea widgets propios (estilo POO) y en la Page solo instáncialos.

Uso de APIs y código deprecated
- No uses APIs deprecated de Flutter.
- Asume la última versión estable de Flutter.
- Si detectas código deprecated existente, reemplázalo por la alternativa recomendada y ajusta el resto del código para que compile sin warnings críticos.

Cuando sea posible para evitar "recrear la rueda", usa paquetes de pub.dev que permitan acelerar el desarrollo al evitar tener que programar ciertas cosas, excepto lo muy especifico donde lo requerimos de una forma puntual.