-- miGanadito Control - esquema completo MariaDB/MySQL
-- Generado a partir de las consultas usadas por app.py y el backup legado.
-- Uso:
--   mysql -u TU_USUARIO -p < database_complete.sql

CREATE DATABASE IF NOT EXISTS `Proyecto_Ganaderia2`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `Proyecto_Ganaderia2`;

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `Aplicaciones`;
DROP TABLE IF EXISTS `Config_Dosis`;
DROP TABLE IF EXISTS `Atencion_Animal`;
DROP TABLE IF EXISTS `Servicios`;
DROP TABLE IF EXISTS `Ventas`;
DROP TABLE IF EXISTS `Seguimiento_vet`;
DROP TABLE IF EXISTS `Registro_SINIGA`;
DROP TABLE IF EXISTS `Pesajes`;
DROP TABLE IF EXISTS `Animales`;
DROP TABLE IF EXISTS `Predios`;
DROP TABLE IF EXISTS `Municipios`;
DROP TABLE IF EXISTS `Estados`;
DROP TABLE IF EXISTS `Veterinario`;
DROP TABLE IF EXISTS `Productores`;
DROP TABLE IF EXISTS `solicitudes_veterinario_productor`;
DROP TABLE IF EXISTS `Usuarios`;
DROP TABLE IF EXISTS `Rol`;
DROP TABLE IF EXISTS `tratamientos`;
DROP TABLE IF EXISTS `insumos_medicos`;
DROP TABLE IF EXISTS `Razas`;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE `Rol` (
  `id_rol` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(50) NOT NULL,
  PRIMARY KEY (`id_rol`),
  UNIQUE KEY `uk_rol_nombre` (`nombre`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Usuarios` (
  `id_usuario` INT NOT NULL AUTO_INCREMENT,
  `usuario` VARCHAR(50) NOT NULL,
  `email` VARCHAR(255) DEFAULT NULL,
  `password` VARCHAR(255) NOT NULL,
  `fk_rol` INT NOT NULL,
  `permiso_datos_completos` TINYINT(1) NOT NULL DEFAULT 0,
  `solicitud_permiso_datos` TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id_usuario`),
  UNIQUE KEY `uk_usuarios_usuario` (`usuario`),
  UNIQUE KEY `uk_usuarios_email` (`email`),
  KEY `idx_usuarios_fk_rol` (`fk_rol`),
  CONSTRAINT `fk_usuarios_rol`
    FOREIGN KEY (`fk_rol`) REFERENCES `Rol` (`id_rol`)
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Productores` (
  `pk_productor` INT NOT NULL AUTO_INCREMENT,
  `fk_usuario` INT NOT NULL,
  `nombre` VARCHAR(255) DEFAULT NULL,
  `apellido_pat` VARCHAR(255) DEFAULT NULL,
  `apellido_mat` VARCHAR(255) DEFAULT NULL,
  `RFC` VARCHAR(50) DEFAULT NULL,
  `foto_fierro` MEDIUMBLOB DEFAULT NULL,
  PRIMARY KEY (`pk_productor`),
  UNIQUE KEY `uk_productores_usuario` (`fk_usuario`),
  UNIQUE KEY `uk_productores_rfc` (`RFC`),
  CONSTRAINT `fk_productores_usuarios`
    FOREIGN KEY (`fk_usuario`) REFERENCES `Usuarios` (`id_usuario`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Veterinario` (
  `id_veterinario` INT NOT NULL AUTO_INCREMENT,
  `fk_usuario` INT NOT NULL,
  `nombre` VARCHAR(100) NOT NULL,
  `apellidos` VARCHAR(120) NOT NULL,
  `cedula` VARCHAR(50) NOT NULL,
  `direccion_consultorio` TEXT DEFAULT NULL,
  `telefono` VARCHAR(20) DEFAULT NULL,
  PRIMARY KEY (`id_veterinario`),
  UNIQUE KEY `uk_veterinario_usuario` (`fk_usuario`),
  UNIQUE KEY `uk_veterinario_cedula` (`cedula`),
  CONSTRAINT `fk_veterinario_usuarios`
    FOREIGN KEY (`fk_usuario`) REFERENCES `Usuarios` (`id_usuario`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `solicitudes_veterinario_productor` (
  `id_solicitud` INT NOT NULL AUTO_INCREMENT,
  `fk_usuario_veterinario` INT NOT NULL,
  `fk_productor` INT NOT NULL,
  `nota` TEXT DEFAULT NULL,
  `estado` VARCHAR(20) NOT NULL DEFAULT 'pendiente',
  `fecha_solicitud` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `fecha_respuesta` TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (`id_solicitud`),
  UNIQUE KEY `uk_solicitud_vet_productor` (`fk_usuario_veterinario`, `fk_productor`),
  KEY `idx_solicitudes_productor` (`fk_productor`),
  CONSTRAINT `fk_solicitudes_vet_usuario`
    FOREIGN KEY (`fk_usuario_veterinario`) REFERENCES `Usuarios` (`id_usuario`)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT `fk_solicitudes_productor`
    FOREIGN KEY (`fk_productor`) REFERENCES `Productores` (`pk_productor`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Estados` (
  `pk_estado` INT UNSIGNED NOT NULL,
  `Nombre` VARCHAR(80) NOT NULL,
  PRIMARY KEY (`pk_estado`),
  UNIQUE KEY `uk_estados_nombre` (`Nombre`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Municipios` (
  `pk_municipio` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `Nombre` VARCHAR(100) NOT NULL,
  `fk_estado` INT UNSIGNED NOT NULL,
  PRIMARY KEY (`pk_municipio`),
  KEY `idx_municipios_estado` (`fk_estado`),
  CONSTRAINT `fk_municipios_estados`
    FOREIGN KEY (`fk_estado`) REFERENCES `Estados` (`pk_estado`)
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Razas` (
  `pk_raza` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) NOT NULL,
  `origen` VARCHAR(100) NOT NULL DEFAULT 'Sin registro',
  `color` VARCHAR(100) DEFAULT 'Sin definir',
  PRIMARY KEY (`pk_raza`),
  UNIQUE KEY `uk_razas_nombre` (`nombre`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Predios` (
  `pk_predio` INT NOT NULL AUTO_INCREMENT,
  `direccion` VARCHAR(255) DEFAULT NULL,
  `fk_estado` INT UNSIGNED NOT NULL,
  `fk_municipio` INT UNSIGNED NOT NULL,
  `fk_productor` INT NOT NULL,
  `nom_rancho` VARCHAR(100) DEFAULT 'No cuenta con nombre',
  `upp` VARCHAR(50) DEFAULT NULL,
  PRIMARY KEY (`pk_predio`),
  UNIQUE KEY `uk_predios_upp` (`upp`),
  KEY `idx_predios_estado` (`fk_estado`),
  KEY `idx_predios_municipio` (`fk_municipio`),
  KEY `idx_predios_productor` (`fk_productor`),
  CONSTRAINT `fk_predios_estados`
    FOREIGN KEY (`fk_estado`) REFERENCES `Estados` (`pk_estado`)
    ON UPDATE CASCADE,
  CONSTRAINT `fk_predios_municipios`
    FOREIGN KEY (`fk_municipio`) REFERENCES `Municipios` (`pk_municipio`)
    ON UPDATE CASCADE,
  CONSTRAINT `fk_predios_productores`
    FOREIGN KEY (`fk_productor`) REFERENCES `Productores` (`pk_productor`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Animales` (
  `pk_animal` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) NOT NULL,
  `fecha_nacimiento` DATE NOT NULL,
  `cruze` VARCHAR(255) NOT NULL DEFAULT 'Sin conocer',
  `foto_perfil` MEDIUMBLOB DEFAULT NULL,
  `foto_lateral` MEDIUMBLOB DEFAULT NULL,
  `foto_arete` MEDIUMBLOB DEFAULT NULL,
  `fk_productor` INT DEFAULT NULL,
  `fk_raza` INT DEFAULT NULL,
  `fk_predio` INT DEFAULT NULL,
  `sexo` ENUM('M','H') NOT NULL,
  `peso_actual` DECIMAL(10,2) DEFAULT NULL,
  `fk_animal` INT DEFAULT NULL,
  `estatus` ENUM('Activo','Baja (Muerto)','Vendido') NOT NULL DEFAULT 'Activo',
  PRIMARY KEY (`pk_animal`),
  KEY `idx_animales_productor` (`fk_productor`),
  KEY `idx_animales_raza` (`fk_raza`),
  KEY `idx_animales_predio` (`fk_predio`),
  KEY `idx_animales_madre` (`fk_animal`),
  KEY `idx_animales_estatus` (`estatus`),
  CONSTRAINT `fk_animales_productores`
    FOREIGN KEY (`fk_productor`) REFERENCES `Productores` (`pk_productor`)
    ON DELETE SET NULL
    ON UPDATE CASCADE,
  CONSTRAINT `fk_animales_razas`
    FOREIGN KEY (`fk_raza`) REFERENCES `Razas` (`pk_raza`)
    ON DELETE SET NULL
    ON UPDATE CASCADE,
  CONSTRAINT `fk_animales_predios`
    FOREIGN KEY (`fk_predio`) REFERENCES `Predios` (`pk_predio`)
    ON DELETE SET NULL
    ON UPDATE CASCADE,
  CONSTRAINT `fk_animales_madre`
    FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Registro_SINIGA` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `fk_animal` INT DEFAULT NULL,
  `arete` VARCHAR(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_siniga_animal` (`fk_animal`),
  UNIQUE KEY `uk_siniga_arete` (`arete`),
  CONSTRAINT `fk_siniga_animales`
    FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Pesajes` (
  `pk_pesaje` INT NOT NULL AUTO_INCREMENT,
  `pesaje` DECIMAL(10,2) NOT NULL,
  `fecha` DATE NOT NULL,
  `fk_animal` INT DEFAULT NULL,
  PRIMARY KEY (`pk_pesaje`),
  KEY `idx_pesajes_animal` (`fk_animal`),
  CONSTRAINT `fk_pesajes_animales`
    FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `tratamientos` (
  `pk_tratamiento` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) NOT NULL,
  `impacto` VARCHAR(30) NOT NULL DEFAULT 'Preventivo',
  `descripcion` TEXT DEFAULT NULL,
  PRIMARY KEY (`pk_tratamiento`),
  UNIQUE KEY `uk_tratamientos_nombre` (`nombre`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Seguimiento_vet` (
  `pk_segui_vet` INT NOT NULL AUTO_INCREMENT,
  `fk_animal` INT DEFAULT NULL,
  `fk_tratamiento` INT DEFAULT NULL,
  `tipo_tratamiento` VARCHAR(100) NOT NULL DEFAULT 'Chequeo',
  `medicamento` VARCHAR(120) DEFAULT NULL,
  `fecha_actual` DATE NOT NULL,
  `prox_fecha` DATE DEFAULT NULL,
  PRIMARY KEY (`pk_segui_vet`),
  KEY `idx_seguimiento_animal` (`fk_animal`),
  KEY `idx_seguimiento_tratamiento` (`fk_tratamiento`),
  KEY `idx_seguimiento_prox_fecha` (`prox_fecha`),
  CONSTRAINT `fk_seguimiento_animales`
    FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT `fk_seguimiento_tratamientos`
    FOREIGN KEY (`fk_tratamiento`) REFERENCES `tratamientos` (`pk_tratamiento`)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Ventas` (
  `pk_venta` INT NOT NULL AUTO_INCREMENT,
  `fk_animal` INT DEFAULT NULL,
  `fk_pesaje` INT DEFAULT NULL,
  `clave` VARCHAR(100) DEFAULT NULL,
  `precio` DECIMAL(12,2) NOT NULL DEFAULT 0.00,
  `fecha_venta` DATE NOT NULL,
  PRIMARY KEY (`pk_venta`),
  KEY `idx_ventas_animal` (`fk_animal`),
  KEY `idx_ventas_pesaje` (`fk_pesaje`),
  KEY `idx_ventas_fecha` (`fecha_venta`),
  CONSTRAINT `fk_ventas_animales`
    FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
    ON DELETE SET NULL
    ON UPDATE CASCADE,
  CONSTRAINT `fk_ventas_pesajes`
    FOREIGN KEY (`fk_pesaje`) REFERENCES `Pesajes` (`pk_pesaje`)
    ON DELETE SET NULL
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `insumos_medicos` (
  `id_insumo` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) DEFAULT NULL,
  `categoria` VARCHAR(50) DEFAULT NULL,
  `concentracion` DECIMAL(10,2) DEFAULT NULL,
  `stock_actual` DECIMAL(10,2) DEFAULT 0.00,
  `fecha_caducidad` DATE DEFAULT NULL,
  `dias_retiro` INT DEFAULT NULL,
  PRIMARY KEY (`id_insumo`),
  KEY `idx_insumos_categoria` (`categoria`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Servicios` (
  `id_servicio` INT NOT NULL AUTO_INCREMENT,
  `fk_veterinario` INT NOT NULL,
  `fk_productor` INT NOT NULL,
  `fecha_servicio` DATE NOT NULL,
  `total_cobrado` DECIMAL(10,2) DEFAULT NULL,
  PRIMARY KEY (`id_servicio`),
  KEY `idx_servicios_veterinario` (`fk_veterinario`),
  KEY `idx_servicios_productor` (`fk_productor`),
  CONSTRAINT `fk_servicios_veterinario`
    FOREIGN KEY (`fk_veterinario`) REFERENCES `Veterinario` (`id_veterinario`)
    ON UPDATE CASCADE,
  CONSTRAINT `fk_servicios_productores`
    FOREIGN KEY (`fk_productor`) REFERENCES `Productores` (`pk_productor`)
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Atencion_Animal` (
  `id_atencion` INT NOT NULL AUTO_INCREMENT,
  `fk_servicio` INT NOT NULL,
  `fk_animal` INT NOT NULL,
  `diagnostico` TEXT DEFAULT NULL,
  PRIMARY KEY (`id_atencion`),
  KEY `idx_atencion_servicio` (`fk_servicio`),
  KEY `idx_atencion_animal` (`fk_animal`),
  CONSTRAINT `fk_atencion_servicios`
    FOREIGN KEY (`fk_servicio`) REFERENCES `Servicios` (`id_servicio`)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT `fk_atencion_animales`
    FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Aplicaciones` (
  `id_aplicacion` INT NOT NULL AUTO_INCREMENT,
  `fk_atencion` INT NOT NULL,
  `fk_insumo` INT NOT NULL,
  `peso_actual` DECIMAL(10,2) DEFAULT NULL,
  `dosis_calculada_ml` DECIMAL(10,2) DEFAULT NULL,
  `fecha_hora` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id_aplicacion`),
  KEY `idx_aplicaciones_atencion` (`fk_atencion`),
  KEY `idx_aplicaciones_insumo` (`fk_insumo`),
  CONSTRAINT `fk_aplicaciones_atencion`
    FOREIGN KEY (`fk_atencion`) REFERENCES `Atencion_Animal` (`id_atencion`)
    ON DELETE CASCADE
    ON UPDATE CASCADE,
  CONSTRAINT `fk_aplicaciones_insumos`
    FOREIGN KEY (`fk_insumo`) REFERENCES `insumos_medicos` (`id_insumo`)
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `Config_Dosis` (
  `id_config` INT NOT NULL AUTO_INCREMENT,
  `fk_insumo` INT NOT NULL,
  `mg_por_kg` DECIMAL(10,2) DEFAULT NULL,
  `especie_destino` VARCHAR(50) DEFAULT NULL,
  PRIMARY KEY (`id_config`),
  KEY `idx_config_dosis_insumo` (`fk_insumo`),
  CONSTRAINT `fk_config_dosis_insumos`
    FOREIGN KEY (`fk_insumo`) REFERENCES `insumos_medicos` (`id_insumo`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `Rol` (`id_rol`, `nombre`) VALUES
  (1, 'Administrador'),
  (2, 'Productor'),
  (3, 'Veterinario'),
  (4, 'Comprador')
ON DUPLICATE KEY UPDATE `nombre` = VALUES(`nombre`);

-- Usuario inicial:
--   usuario: admin
--   password: AdminGanadito2026!
-- La app acepta contraseñas antiguas en texto plano y después puedes cambiarla.
INSERT INTO `Usuarios` (`id_usuario`, `usuario`, `email`, `password`, `fk_rol`, `permiso_datos_completos`)
VALUES (1, 'admin', 'admin@miganadito.local', 'AdminGanadito2026!', 1, 1)
ON DUPLICATE KEY UPDATE `fk_rol` = VALUES(`fk_rol`);

INSERT INTO `Estados` (`pk_estado`, `Nombre`) VALUES
  (1, 'Aguascalientes'),
  (2, 'Baja California'),
  (3, 'Baja California Sur'),
  (4, 'Campeche'),
  (5, 'Coahuila'),
  (6, 'Colima'),
  (7, 'Chiapas'),
  (8, 'Chihuahua'),
  (9, 'Ciudad de Mexico'),
  (10, 'Durango'),
  (11, 'Guanajuato'),
  (12, 'Guerrero'),
  (13, 'Hidalgo'),
  (14, 'Jalisco'),
  (15, 'Mexico'),
  (16, 'Michoacan'),
  (17, 'Morelos'),
  (18, 'Nayarit'),
  (19, 'Nuevo Leon'),
  (20, 'Oaxaca'),
  (21, 'Puebla'),
  (22, 'Queretaro'),
  (23, 'Quintana Roo'),
  (24, 'San Luis Potosi'),
  (25, 'Sinaloa'),
  (26, 'Sonora'),
  (27, 'Tabasco'),
  (28, 'Tamaulipas'),
  (29, 'Tlaxcala'),
  (30, 'Veracruz'),
  (31, 'Yucatan'),
  (32, 'Zacatecas')
ON DUPLICATE KEY UPDATE `Nombre` = VALUES(`Nombre`);

INSERT INTO `Municipios` (`pk_municipio`, `Nombre`, `fk_estado`) VALUES
  (27001, 'Balancan', 27),
  (27002, 'Cardenas', 27),
  (27003, 'Centla', 27),
  (27004, 'Centro', 27),
  (27005, 'Comalcalco', 27),
  (27006, 'Cunduacan', 27),
  (27007, 'Emiliano Zapata', 27),
  (27008, 'Huimanguillo', 27),
  (27009, 'Jalapa', 27),
  (27010, 'Jalpa de Mendez', 27),
  (27011, 'Jonuta', 27),
  (27012, 'Macuspana', 27),
  (27013, 'Nacajuca', 27),
  (27014, 'Paraiso', 27),
  (27015, 'Tacotalpa', 27),
  (27016, 'Teapa', 27),
  (27017, 'Tenosique', 27)
ON DUPLICATE KEY UPDATE
  `Nombre` = VALUES(`Nombre`),
  `fk_estado` = VALUES(`fk_estado`);

INSERT INTO `Razas` (`nombre`, `origen`, `color`) VALUES
  ('Beefmaster', 'Estados Unidos', 'Rojo'),
  ('Cebu', 'Asia', 'Gris'),
  ('Charolais', 'Francia', 'Blanco'),
  ('Gyr', 'India', 'Rojo y blanco'),
  ('Guzerat', 'India', 'Gris'),
  ('Nelore', 'India', 'Blanco'),
  ('Sardo Negro', 'Mexico', 'Negro y blanco'),
  ('Simmental', 'Suiza', 'Rojo y blanco')
ON DUPLICATE KEY UPDATE
  `origen` = VALUES(`origen`),
  `color` = VALUES(`color`);

INSERT INTO `tratamientos` (`nombre`, `impacto`, `descripcion`) VALUES
  ('Chequeo general', 'Preventivo', 'Revision general del animal.'),
  ('Vacunacion', 'Preventivo', 'Aplicacion de vacuna programada.'),
  ('Desparasitacion', 'Preventivo', 'Control de parasitos internos o externos.'),
  ('Tratamiento curativo', 'Grave', 'Atencion por enfermedad o lesion.'),
  ('Control reproductivo', 'Seguimiento', 'Revision reproductiva o gestacional.')
ON DUPLICATE KEY UPDATE
  `impacto` = VALUES(`impacto`),
  `descripcion` = VALUES(`descripcion`);

INSERT INTO `insumos_medicos`
  (`nombre`, `categoria`, `concentracion`, `stock_actual`, `dias_retiro`)
VALUES
  ('Ivermectina', 'Desparasitante', 1.00, 0.00, 28),
  ('Oxitetraciclina', 'Antibiotico', 10.00, 0.00, 21),
  ('Penicilina', 'Antibiotico', 20.00, 0.00, 10),
  ('Complejo B', 'Vitamina', 0.00, 0.00, 0),
  ('Vacuna clostridial', 'Vacuna', 0.00, 0.00, 21),
  ('Bano garrapaticida', 'Ectoparasiticida', 0.00, 0.00, 0);
