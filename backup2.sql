/*M!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19  Distrib 10.11.14-MariaDB, for debian-linux-gnu (x86_64)
--
-- Host: localhost    Database: Proyecto_Ganaderia2
-- ------------------------------------------------------
-- Server version	10.11.14-MariaDB-0ubuntu0.24.04.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Current Database: `Proyecto_Ganaderia2`
--

CREATE DATABASE /*!32312 IF NOT EXISTS*/ `Proyecto_Ganaderia2` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci */;

USE `Proyecto_Ganaderia2`;

--
-- Table structure for table `Animales`
--

DROP TABLE IF EXISTS `Animales`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Animales` (
  `pk_animal` int(11) NOT NULL AUTO_INCREMENT,
  `nombre` varchar(100) NOT NULL,
  `fecha_nacimiento` date NOT NULL,
  `cruze` text NOT NULL DEFAULT 'Sin conocer',
  `foto_perfil` mediumblob DEFAULT NULL,
  `foto_lateral` mediumblob DEFAULT NULL,
  `fk_productor` int(11) DEFAULT NULL,
  `fk_raza` int(11) DEFAULT NULL,
  `sexo` enum('M','H') NOT NULL,
  `peso_actual` float DEFAULT NULL,
  `fk_animal` int(11) DEFAULT NULL,
  PRIMARY KEY (`pk_animal`),
  KEY `fk_productor` (`fk_productor`),
  KEY `fk_raza` (`fk_raza`),
  KEY `fk_animal` (`fk_animal`),
  CONSTRAINT `Animales_ibfk_1` FOREIGN KEY (`fk_productor`) REFERENCES `Productores` (`pk_productor`),
  CONSTRAINT `Animales_ibfk_2` FOREIGN KEY (`fk_raza`) REFERENCES `Razas` (`pk_raza`),
  CONSTRAINT `Animales_ibfk_3` FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Animales`
--

LOCK TABLES `Animales` WRITE;
/*!40000 ALTER TABLE `Animales` DISABLE KEYS */;
/*!40000 ALTER TABLE `Animales` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Aplicaciones`
--

DROP TABLE IF EXISTS `Aplicaciones`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Aplicaciones` (
  `id_aplicacion` int(11) NOT NULL AUTO_INCREMENT,
  `fk_atencion` int(11) NOT NULL,
  `fk_insumo` int(11) NOT NULL,
  `peso_actual` float DEFAULT NULL,
  `dosis_calculada_ml` float DEFAULT NULL,
  `fecha_hora` datetime DEFAULT NULL,
  PRIMARY KEY (`id_aplicacion`),
  KEY `fk_atencion` (`fk_atencion`),
  KEY `fk_insumo` (`fk_insumo`),
  CONSTRAINT `Aplicaciones_ibfk_1` FOREIGN KEY (`fk_atencion`) REFERENCES `Atencion_Animal` (`id_atencion`),
  CONSTRAINT `Aplicaciones_ibfk_2` FOREIGN KEY (`fk_insumo`) REFERENCES `Insumos_Medicos` (`id_insumo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Aplicaciones`
--

LOCK TABLES `Aplicaciones` WRITE;
/*!40000 ALTER TABLE `Aplicaciones` DISABLE KEYS */;
/*!40000 ALTER TABLE `Aplicaciones` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Atencion_Animal`
--

DROP TABLE IF EXISTS `Atencion_Animal`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Atencion_Animal` (
  `id_atencion` int(11) NOT NULL AUTO_INCREMENT,
  `fk_servicio` int(11) NOT NULL,
  `fk_animal` int(11) NOT NULL,
  `diagnostico` text DEFAULT NULL,
  PRIMARY KEY (`id_atencion`),
  KEY `fk_servicio` (`fk_servicio`),
  KEY `fk_animal` (`fk_animal`),
  CONSTRAINT `Atencion_Animal_ibfk_1` FOREIGN KEY (`fk_servicio`) REFERENCES `Servicios` (`id_servicio`),
  CONSTRAINT `Atencion_Animal_ibfk_2` FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Atencion_Animal`
--

LOCK TABLES `Atencion_Animal` WRITE;
/*!40000 ALTER TABLE `Atencion_Animal` DISABLE KEYS */;
/*!40000 ALTER TABLE `Atencion_Animal` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Config_Dosis`
--

DROP TABLE IF EXISTS `Config_Dosis`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Config_Dosis` (
  `id_config` int(11) NOT NULL AUTO_INCREMENT,
  `fk_insumo` int(11) NOT NULL,
  `mg_por_kg` float DEFAULT NULL,
  `especie_destino` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id_config`),
  KEY `fk_insumo` (`fk_insumo`),
  CONSTRAINT `Config_Dosis_ibfk_1` FOREIGN KEY (`fk_insumo`) REFERENCES `Insumos_Medicos` (`id_insumo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Config_Dosis`
--

LOCK TABLES `Config_Dosis` WRITE;
/*!40000 ALTER TABLE `Config_Dosis` DISABLE KEYS */;
/*!40000 ALTER TABLE `Config_Dosis` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Estados`
--

DROP TABLE IF EXISTS `Estados`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Estados` (
  `pk_estado` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `Nombre` varchar(50) NOT NULL DEFAULT 'Sin registro',
  PRIMARY KEY (`pk_estado`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Estados`
--

LOCK TABLES `Estados` WRITE;
/*!40000 ALTER TABLE `Estados` DISABLE KEYS */;
/*!40000 ALTER TABLE `Estados` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Insumos_Medicos`
--

DROP TABLE IF EXISTS `Insumos_Medicos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Insumos_Medicos` (
  `id_insumo` int(11) NOT NULL AUTO_INCREMENT,
  `nombre` varchar(100) DEFAULT NULL,
  `categoria` varchar(50) DEFAULT NULL,
  `concentracion` float DEFAULT NULL,
  `stock_actual` float DEFAULT NULL,
  `fecha_caducidad` date DEFAULT NULL,
  `dias_retiro` int(11) DEFAULT NULL,
  PRIMARY KEY (`id_insumo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Insumos_Medicos`
--

LOCK TABLES `Insumos_Medicos` WRITE;
/*!40000 ALTER TABLE `Insumos_Medicos` DISABLE KEYS */;
/*!40000 ALTER TABLE `Insumos_Medicos` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Municipios`
--

DROP TABLE IF EXISTS `Municipios`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Municipios` (
  `pk_municipio` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `Nombre` varchar(80) NOT NULL,
  `fk_estado` int(10) unsigned NOT NULL,
  PRIMARY KEY (`pk_municipio`),
  KEY `fk_estado` (`fk_estado`),
  CONSTRAINT `Municipios_ibfk_1` FOREIGN KEY (`fk_estado`) REFERENCES `Estados` (`pk_estado`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Municipios`
--

LOCK TABLES `Municipios` WRITE;
/*!40000 ALTER TABLE `Municipios` DISABLE KEYS */;
/*!40000 ALTER TABLE `Municipios` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Pesajes`
--

DROP TABLE IF EXISTS `Pesajes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Pesajes` (
  `pk_pesaje` int(11) NOT NULL AUTO_INCREMENT,
  `pesaje` float NOT NULL,
  `fecha` date NOT NULL,
  `fk_animal` int(11) DEFAULT NULL,
  PRIMARY KEY (`pk_pesaje`),
  KEY `fk_animal` (`fk_animal`),
  CONSTRAINT `Pesajes_ibfk_1` FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Pesajes`
--

LOCK TABLES `Pesajes` WRITE;
/*!40000 ALTER TABLE `Pesajes` DISABLE KEYS */;
/*!40000 ALTER TABLE `Pesajes` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Predios`
--

DROP TABLE IF EXISTS `Predios`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Predios` (
  `pk_predio` int(11) NOT NULL AUTO_INCREMENT,
  `direccion` varchar(255) DEFAULT NULL,
  `fk_estado` int(10) unsigned NOT NULL,
  `fk_municipio` int(10) unsigned NOT NULL,
  `fk_productor` int(11) NOT NULL,
  `nom_rancho` varchar(50) DEFAULT 'No cuenta con nombre',
  `UPP` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`pk_predio`),
  UNIQUE KEY `UPP` (`UPP`),
  KEY `fk_estado` (`fk_estado`),
  KEY `fk_municipio` (`fk_municipio`),
  KEY `fk_productor` (`fk_productor`),
  CONSTRAINT `Predios_ibfk_1` FOREIGN KEY (`fk_estado`) REFERENCES `Estados` (`pk_estado`),
  CONSTRAINT `Predios_ibfk_2` FOREIGN KEY (`fk_municipio`) REFERENCES `Municipios` (`pk_municipio`),
  CONSTRAINT `Predios_ibfk_3` FOREIGN KEY (`fk_productor`) REFERENCES `Productores` (`pk_productor`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Predios`
--

LOCK TABLES `Predios` WRITE;
/*!40000 ALTER TABLE `Predios` DISABLE KEYS */;
/*!40000 ALTER TABLE `Predios` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `Productores`
--

DROP TABLE IF EXISTS `Productores`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Productores` (
  `pk_productor` int(11) NOT NULL AUTO_INCREMENT,
  `fk_usuario` int(11) NOT NULL,
  `nombre` varchar(255) DEFAULT NULL,
  `apellido_pat` varchar(255) DEFAULT NULL,
  `apellido_mat` varchar(255) DEFAULT NULL,
  `RFC` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`pk_productor`),
  UNIQUE KEY `RFC` (`RFC`),
  KEY `fk_usuario` (`fk_usuario`),
  CONSTRAINT `Productores_ibfk_1` FOREIGN KEY (`fk_usuario`) REFERENCES `Usuarios` (`id_usuario`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `Productores`
--

LOCK TABLES `Productores` WRITE;
UNLOCK TABLES;


DROP TABLE IF EXISTS `Razas`;
CREATE TABLE `Razas` (
  `pk_raza` int(11) NOT NULL AUTO_INCREMENT,
  `nombre` varchar(100) NOT NULL,
  `origen` varchar(100) NOT NULL DEFAULT 'Sin registro',
  `color` varchar(100) DEFAULT 'Sin definir',
  PRIMARY KEY (`pk_raza`),
  UNIQUE KEY `nombre` (`nombre`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

LOCK TABLES `Razas` WRITE;

UNLOCK TABLES;


DROP TABLE IF EXISTS `Registro_SINIGA`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Registro_SINIGA` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `fk_animal` int(11) DEFAULT NULL,
  `arete` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `fk_animal` (`fk_animal`),
  CONSTRAINT `Registro_SINIGA_ibfk_1` FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

LOCK TABLES `Registro_SINIGA` WRITE;

UNLOCK TABLES;

DROP TABLE IF EXISTS `Rol`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Rol` (
  `id_rol` int(11) NOT NULL AUTO_INCREMENT,
  `nombre` varchar(50) NOT NULL,
  PRIMARY KEY (`id_rol`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

LOCK TABLES `Rol` WRITE;

UNLOCK TABLES;

--
-- Table structure for table `Seguimiento_vet`
--

DROP TABLE IF EXISTS `Seguimiento_vet`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Seguimiento_vet` (
  `pk_segui_vet` int(11) NOT NULL AUTO_INCREMENT,
  `fk_animal` int(11) DEFAULT NULL,
  `tipo_tratamiento` text NOT NULL DEFAULT 'Chequeo',
  `fecha_actual` date NOT NULL,
  `prox_fecha` date DEFAULT NULL,
  PRIMARY KEY (`pk_segui_vet`),
  KEY `fk_animal` (`fk_animal`),
  CONSTRAINT `Seguimiento_vet_ibfk_1` FOREIGN KEY (`fk_animal`) REFERENCES `Animales` (`pk_animal`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

LOCK TABLES `Seguimiento_vet` WRITE;

UNLOCK TABLES;


DROP TABLE IF EXISTS `Servicios`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `Servicios` (
  `id_servicio` int(11) NOT NULL AUTO_INCREMENT,
  `fk_veterinario` int(11) NOT NULL,
  `fk_productor` int(11) NOT NULL,
  `fecha_servicio` date NOT NULL,
  `total_cobrado` decimal(10,2) DEFAULT NULL,
  PRIMARY KEY (`id_servicio`),
  KEY `fk_veterinario` (`fk_veterinario`),
  KEY `fk_productor` (`fk_productor`),
  CONSTRAINT `Servicios_ibfk_1` FOREIGN KEY (`fk_veterinario`) REFERENCES `Veterinario` (`id_veterinario`),
  CONSTRAINT `Servicios_ibfk_2` FOREIGN KEY (`fk_productor`) REFERENCES `Productores` (`pk_productor`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

LOCK TABLES `Servicios` WRITE;

UNLOCK TABLES;


DROP TABLE IF EXISTS `Usuarios`;

CREATE TABLE `Usuarios` (
  `id_usuario` int(11) NOT NULL AUTO_INCREMENT,
  `usuario` varchar(50) NOT NULL,
  `password` varchar(100) NOT NULL,
  `fk_rol` int(11) NOT NULL,
  PRIMARY KEY (`id_usuario`),
  UNIQUE KEY `usuario` (`usuario`),
  KEY `fk_rol` (`fk_rol`),
  CONSTRAINT `Usuarios_ibfk_1` FOREIGN KEY (`fk_rol`) REFERENCES `Rol` (`id_rol`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

LOCK TABLES `Usuarios` WRITE;

UNLOCK TABLES;


DROP TABLE IF EXISTS `Veterinario`;

CREATE TABLE `Veterinario` (
  `id_veterinario` int(11) NOT NULL AUTO_INCREMENT,
  `fk_usuario` int(11) NOT NULL,
  `nombre` varchar(50) NOT NULL,
  `apellidos` varchar(50) NOT NULL,
  `cedula` varchar(50) NOT NULL,
  `direccion_consultorio` text DEFAULT 'Consultas a domicilio',
  `telefono` int(10) DEFAULT NULL,
  PRIMARY KEY (`id_veterinario`),
  KEY `fk_usuario` (`fk_usuario`),
  CONSTRAINT `Veterinario_ibfk_1` FOREIGN KEY (`fk_usuario`) REFERENCES `Usuarios` (`id_usuario`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

LOCK TABLES `Veterinario` WRITE;

UNLOCK TABLES;
