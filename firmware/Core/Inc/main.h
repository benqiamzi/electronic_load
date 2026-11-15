/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define STATUS_Pin GPIO_PIN_13
#define STATUS_GPIO_Port GPIOC
#define V_SENSE_SEL0_Pin GPIO_PIN_1
#define V_SENSE_SEL0_GPIO_Port GPIOC
#define V_SENSE_SEL1_Pin GPIO_PIN_2
#define V_SENSE_SEL1_GPIO_Port GPIOC
#define V_ISENSE_Pin GPIO_PIN_4
#define V_ISENSE_GPIO_Port GPIOA
#define V_VSENSE_Pin GPIO_PIN_5
#define V_VSENSE_GPIO_Port GPIOA
#define V_TSENSE_Pin GPIO_PIN_6
#define V_TSENSE_GPIO_Port GPIOA
#define VREF_PWM_Pin GPIO_PIN_10
#define VREF_PWM_GPIO_Port GPIOB
#define FAN_PWM_Pin GPIO_PIN_8
#define FAN_PWM_GPIO_Port GPIOC
#define DAC_SYNC_Pin GPIO_PIN_15
#define DAC_SYNC_GPIO_Port GPIOA
#define DAC_SCLK_Pin GPIO_PIN_10
#define DAC_SCLK_GPIO_Port GPIOC
#define DAC_DIN_Pin GPIO_PIN_12
#define DAC_DIN_GPIO_Port GPIOC
#define INA226_INT_Pin GPIO_PIN_5
#define INA226_INT_GPIO_Port GPIOB
#define INA226_SCL_Pin GPIO_PIN_6
#define INA226_SCL_GPIO_Port GPIOB
#define INA226_SDA_Pin GPIO_PIN_7
#define INA226_SDA_GPIO_Port GPIOB
#define TC_EN_Pin GPIO_PIN_9
#define TC_EN_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
