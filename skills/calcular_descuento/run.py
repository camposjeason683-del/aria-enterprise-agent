import sys
import json

def main():
    try:
        input_data = json.load(sys.stdin)
        precio = float(input_data.get("precio_original", 0))
        descuento = float(input_data.get("descuento_porcentaje", 0))
        
        ahorro = precio * (descuento / 100.0)
        precio_final = precio - ahorro
        
        output = {
            "precio_original": precio,
            "descuento_porcentaje": descuento,
            "ahorro": ahorro,
            "precio_final": precio_final
        }
        print(json.dumps(output))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
