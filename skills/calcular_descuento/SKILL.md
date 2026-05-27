---
name: calcular_descuento
description: Calcula el precio final de un producto aplicando un descuento porcentual.
parameters:
  type: object
  properties:
    precio_original:
      type: number
      description: El precio original del producto.
    descuento_porcentaje:
      type: number
      description: El porcentaje de descuento a aplicar (0 a 100).
  required:
    - precio_original
    - descuento_porcentaje
---
# Skill: calcular_descuento
Calcula el descuento para un producto y retorna el precio final.
