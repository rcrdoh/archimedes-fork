export default {
  plugins: {
    ...(process.env.NODE_ENV === 'production'
      ? {
          cssnano: {
            preset: [
              'default',
              {
                mergeLonghand: false,
                mergeRules: false,
                normalizeUrl: false,
                discardDuplicates: true,
                minifyFontValues: false,
                reduceIdents: false,
              },
            ],
          },
        }
      : {}),
  },
}