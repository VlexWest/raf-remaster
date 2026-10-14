/*
 * RAF Config.fx  (raf-remaster, not a stock file)
 *
 * Feature switches and tuning for the remaster shaders. tools/build_shaders.py
 * rewrites the values between the BEGIN/END markers from its command line, so
 * a single feature can be turned off for a live A/B test without editing code.
 * Every value is a preprocessor constant: nothing here becomes an effect
 * parameter, so the engine-facing interface stays identical to stock.
 */

#ifndef RAF_CONFIG_INCLUDED
#define RAF_CONFIG_INCLUDED 1

/* RAF-CONFIG-BEGIN */
#define RAF_UNIT_PERPIXEL        1      /* units: light cube / N.L evaluated per pixel        */
#define RAF_UNIT_SPEC            1      /* units: per-pixel Blinn-Phong                       */
#define RAF_UNIT_RIM             1      /* units: gentle rim light on every unit              */
#define RAF_UNIT_SKIN_TBN        1      /* units: skin tangent + binormal with the normal     */
#define RAF_TERRAIN_RELIEF       1      /* terrain: per-pixel relief from the bump map        */
#define RAF_TERRAIN_DETAIL       1      /* terrain: two-scale anti-tiling detail              */
#define RAF_WATER                1      /* water: Schlick fresnel, normal blend, sun glint    */
#define RAF_LIGHT_SIGN           1.0F   /* flip to -1.0F if highlights face away from the sun */
#define RAF_TERRAIN_BUMP_YSIGN   1.0F   /* flip to -1.0F if terrain relief is lit wrong in y  */
#define RAF_UNIT_SPEC_DEFAULT    0.08F  /* spec amount for materials without a spec mask      */
#define RAF_UNIT_SPEC_POWER_MIN  16.0F  /* floor for k_Shininess (stock default is 10)       */
#define RAF_UNIT_RIM_AMOUNT      0.22F
#define RAF_UNIT_RIM_POWER       3.0F
#define RAF_TERRAIN_RELIEF_AMOUNT 0.55F
#define RAF_TERRAIN_DETAIL_AMOUNT 0.40F
#define RAF_TERRAIN_DETAIL_SCALE  0.173F
#define RAF_WATER_REFL_BOOST     0.60F
#define RAF_WATER_GLINT_POWER    220.0F
#define RAF_WATER_GLINT_AMOUNT   2.0F
#define RAF_VS_PROFILE           vs_2_0 /* unit vertex shaders                                */
#define RAF_PS_PROFILE           ps_2_b /* unit, terrain and water pixel shaders (see below)  */
/* RAF-CONFIG-END */

/*
 * Shader profiles. Stock compiled units with the engine's VS_VERSION /
 * PS_VERSION macros, which the engine sets per permutation to the lowest model
 * the enabled flags need (ps_1_1 for every unit without a normal map). Per-pixel
 * lighting needs more (the stock normal-mapped unit PS already uses 63 of the
 * 64 ps_2_0 slots), so we pin the profiles. ps_2_b, not ps_3_0: D3D9 applies
 * fixed-function FOG only for pixel shaders below 3.0, and the game relies on it.
 * ps_2_a is the fallback if a driver rejects ps_2_b (same slot limit).
 */
#define RAF_UNIT_VS  RAF_VS_PROFILE
#define RAF_UNIT_PS  RAF_PS_PROFILE

static const float3 k_RafLuminance = float3(0.30F, 0.59F, 0.11F);

/*
 * RafSafeNormalize: normalize that returns zero (not NaN) for a zero vector,
 * so an unset light direction switches a term off instead of painting black.
 */
float3
RafSafeNormalize(float3 inVector)
{
	float theLengthSq = dot(inVector, inVector);
	return inVector * rsqrt(max(theLengthSq, 1.0e-8F)) * saturate(theLengthSq * 1.0e6F);
}

/*
 * RafAddLinear: add a linear-light term to a colour that is in gamma space
 * (gamma 2.0 approximation: square in, square root out). With a zero term the
 * colour comes back unchanged, so base colours and team colours keep their look.
 */
float3
RafAddLinear(float3 inGammaColor, float3 inLinearTerm)
{
	return sqrt(inGammaColor * inGammaColor + max(inLinearTerm, 0.0F));
}

#endif
