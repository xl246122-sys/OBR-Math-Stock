package com.obrmath.monitor

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

@Immutable
data class ObrFinancialPalette(
    val isDark: Boolean,
    val background: Color,
    val surface: Color,
    val cardContainer: Color,
    val cardElevated: Color,
    val borderSubtle: Color,
    val borderHighlight: Color,
    val textPrimary: Color,
    val textSecondary: Color,
    val textMuted: Color,
    val primaryAccent: Color,
    val primaryContainer: Color,
    val bullish: Color,
    val bullishContainer: Color,
    val bearish: Color,
    val bearishContainer: Color,
    val warning: Color,
    val warningContainer: Color,
    val paperChannel: Color,
    val paperContainer: Color,
    val liveChannel: Color,
    val liveContainer: Color,
    val infoCyan: Color,
    val infoContainer: Color
)

private val DarkFinancialPalette = ObrFinancialPalette(
    isDark = true,
    background = Color(0xFF0A0E17),
    surface = Color(0xFF111827),
    cardContainer = Color(0xFF162032),
    cardElevated = Color(0xFF1E2B42),
    borderSubtle = Color(0xFF283752),
    borderHighlight = Color(0xFF38BDF8),
    textPrimary = Color(0xFFF8FAFC),
    textSecondary = Color(0xFFCBD5E1),
    textMuted = Color(0xFF8193B2),
    primaryAccent = Color(0xFF38BDF8),
    primaryContainer = Color(0xFF0C2D48),
    bullish = Color(0xFF10B981),
    bullishContainer = Color(0xFF063729),
    bearish = Color(0xFFF43F5E),
    bearishContainer = Color(0xFF42101E),
    warning = Color(0xFFF59E0B),
    warningContainer = Color(0xFF3E2706),
    paperChannel = Color(0xFFA78BFA),
    paperContainer = Color(0xFF281B4A),
    liveChannel = Color(0xFF10B981),
    liveContainer = Color(0xFF08392B),
    infoCyan = Color(0xFF22D3EE),
    infoContainer = Color(0xFF0B3544)
)

private val LightFinancialPalette = ObrFinancialPalette(
    isDark = false,
    background = Color(0xFFF1F5F9),
    surface = Color(0xFFFFFFFF),
    cardContainer = Color(0xFFFFFFFF),
    cardElevated = Color(0xFFF8FAFC),
    borderSubtle = Color(0xFFDCE4EE),
    borderHighlight = Color(0xFF0284C7),
    textPrimary = Color(0xFF0F172A),
    textSecondary = Color(0xFF334155),
    textMuted = Color(0xFF64748B),
    primaryAccent = Color(0xFF0284C7),
    primaryContainer = Color(0xFFE0F2FE),
    bullish = Color(0xFF059669),
    bullishContainer = Color(0xFFD1FAE5),
    bearish = Color(0xFFE11D48),
    bearishContainer = Color(0xFFFFE4E6),
    warning = Color(0xFFD97706),
    warningContainer = Color(0xFFFEF3C7),
    paperChannel = Color(0xFF7C3AED),
    paperContainer = Color(0xFFEDE9FE),
    liveChannel = Color(0xFF059669),
    liveContainer = Color(0xFFD1FAE5),
    infoCyan = Color(0xFF0891B2),
    infoContainer = Color(0xFFCFFAFE)
)

internal val LocalObrPalette = staticCompositionLocalOf { DarkFinancialPalette }

private val ObrDarkColorScheme = darkColorScheme(
    primary = DarkFinancialPalette.primaryAccent,
    onPrimary = Color(0xFF041320),
    primaryContainer = DarkFinancialPalette.primaryContainer,
    onPrimaryContainer = Color(0xFFBAE6FD),
    secondary = DarkFinancialPalette.bullish,
    onSecondary = Color(0xFF02241A),
    secondaryContainer = DarkFinancialPalette.bullishContainer,
    onSecondaryContainer = Color(0xFFA7F3D0),
    tertiary = DarkFinancialPalette.paperChannel,
    background = DarkFinancialPalette.background,
    onBackground = DarkFinancialPalette.textPrimary,
    surface = DarkFinancialPalette.surface,
    onSurface = DarkFinancialPalette.textPrimary,
    surfaceVariant = DarkFinancialPalette.cardContainer,
    onSurfaceVariant = DarkFinancialPalette.textSecondary,
    error = DarkFinancialPalette.bearish,
    onError = Color.White,
    errorContainer = DarkFinancialPalette.bearishContainer,
    onErrorContainer = Color(0xFFFECDD3),
    outline = DarkFinancialPalette.borderSubtle
)

private val ObrLightColorScheme = lightColorScheme(
    primary = LightFinancialPalette.primaryAccent,
    onPrimary = Color.White,
    primaryContainer = LightFinancialPalette.primaryContainer,
    onPrimaryContainer = Color(0xFF075985),
    secondary = LightFinancialPalette.bullish,
    onSecondary = Color.White,
    secondaryContainer = LightFinancialPalette.bullishContainer,
    onSecondaryContainer = Color(0xFF065F46),
    tertiary = LightFinancialPalette.paperChannel,
    background = LightFinancialPalette.background,
    onBackground = LightFinancialPalette.textPrimary,
    surface = LightFinancialPalette.surface,
    onSurface = LightFinancialPalette.textPrimary,
    surfaceVariant = LightFinancialPalette.cardElevated,
    onSurfaceVariant = LightFinancialPalette.textSecondary,
    error = LightFinancialPalette.bearish,
    onError = Color.White,
    errorContainer = LightFinancialPalette.bearishContainer,
    onErrorContainer = Color(0xFF9F1239),
    outline = LightFinancialPalette.borderSubtle
)

private val ObrTypography = Typography(
    headlineMedium = TextStyle(
        fontWeight = FontWeight.ExtraBold,
        fontSize = 22.sp,
        lineHeight = 28.sp,
        letterSpacing = (-0.5).sp
    ),
    titleLarge = TextStyle(
        fontWeight = FontWeight.Bold,
        fontSize = 18.sp,
        lineHeight = 24.sp
    ),
    titleMedium = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 15.sp,
        lineHeight = 21.sp
    ),
    titleSmall = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        lineHeight = 18.sp
    ),
    bodyLarge = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp
    ),
    bodyMedium = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 13.sp,
        lineHeight = 19.sp
    ),
    bodySmall = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 17.sp
    ),
    labelLarge = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        lineHeight = 18.sp
    ),
    labelMedium = TextStyle(
        fontFamily = FontFamily.Monospace,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp
    ),
    labelSmall = TextStyle(
        fontFamily = FontFamily.Monospace,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 15.sp
    )
)

@Composable
fun ObrTheme(
    darkTheme: Boolean = true,
    content: @Composable () -> Unit
) {
    val palette = if (darkTheme) DarkFinancialPalette else LightFinancialPalette
    val colorScheme = if (darkTheme) ObrDarkColorScheme else ObrLightColorScheme

    CompositionLocalProvider(LocalObrPalette provides palette) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = ObrTypography,
            content = content
        )
    }
}
