# LLM Comparison for Dispense Extraction

Summary of model performance and OpenRouter pricing (per 1 Million tokens) based on manual testing with the pharmacy dispense reports.

| Model | Speed per page | Accuracy | Prompt Cost (per 1M) | Output Cost (per 1M) | Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Gemini 2.5 Flash** | 3-8 secs | 100% | $0.30 | $2.50 | Best overall. 100% accurate, fast (8s fully filled, 3-4s sparse). |
| **Gemini 3 Flash** | 15-20 secs | 100% | $0.50 | $3.00 | Better but slower (15-20s per page) and slightly more expensive. |
| **Gemini 2.5 Flash Lite**| 5-7 secs | 98% | $0.10 | $0.40 | Very fast (5-7s) and cheap, but slightly drops accuracy (98%) on complex nested structures. |
| **Qwen3-VL-8B** | Variable | ~94% | $0.117 | $0.455 | Unreliable tool calling. If JSON output is enforced, yields ~94% accuracy but misses some info. |
| **Qwen3-VL-32B** | Variable | ~96% | $0.104 | $0.416 | Unreliable tool calling. With enforced JSON, hits ~96% accuracy but still misses some info. |

## Google AI Studio vs OpenRouter Cost Comparison

While OpenRouter offers a convenient unified API, connecting directly to **Google AI Studio** on a Pay-As-You-Go plan offers hidden cost reductions despite having the same base price:

1. **Identical Base Price:** If you just send standard API calls, the pay-as-you-go cost is exactly the same on both platforms ($0.30 Input / $2.50 Output per 1M tokens for Gemini 2.5 Flash). OpenRouter passes through the provider costs without markup.
2. **Context Caching (Up to 75% Reduction):** Google AI Studio allows you to natively cache large documents (like a 21-page PDF). If you run multiple extraction queries against the same cached document, your input token costs drop significantly (often 50-75% cheaper).
3. **Batch API (50% Reduction):** If your dispense extractions are asynchronous (e.g., overnight processing), Google AI Studio's native Batch API offers a flat **50% discount** on all token costs.

**Summary:** For basic synchronous calls, the Pay-As-You-Go cost is identical. However, if you implement **Context Caching** or use the **Batch API** directly through Google AI Studio, you can reduce your API bill by **50% to 75%** compared to standard OpenRouter routing.

**Conclusion:** `Gemini 2.5 Flash` remains the optimal choice for combining high accuracy, complex schema adherence, and fast processing speeds.
