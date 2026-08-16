import mariadb

try:
    conn = mariadb.connect(
        host='172.25.228.151',
        user='jafet22',
        password='2204',
        database='Proyecto_Ganaderia'
    )
    cursor = conn.cursor()
    
    # Verificar si la columna ya existe
    cursor.execute('DESCRIBE Animales')
    cols = [col[0] for col in cursor.fetchall()]
    
    if 'fk_predio' not in cols:
        print('Agregando columna fk_predio...')
        cursor.execute('ALTER TABLE Animales ADD COLUMN fk_predio INT(11) DEFAULT NULL AFTER fk_raza')
        cursor.execute('ALTER TABLE Animales ADD CONSTRAINT fk_animales_predio FOREIGN KEY (fk_predio) REFERENCES Predios(pk_predio)')
        conn.commit()
        print('✓ Columna fk_predio agregada exitosamente')
    else:
        print('✓ La columna fk_predio ya existe')
    
    conn.close()
except Exception as e:
    print(f'Error: {e}')
