-- Token Bucket Lua Script
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local bucket = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if not tokens or not last_refill then
    tokens = capacity
    last_refill = now
else
    local elapsed = math.max(0, now - last_refill)
    local refill = elapsed * refill_rate
    tokens = math.min(capacity, tokens + refill)
    -- update last_refill to now, but keep track of fractional tokens by adjusting last_refill?
    -- for simplicity, just set last_refill = now
    last_refill = now
end

if tokens >= cost then
    tokens = tokens - cost
    redis.call("HMSET", key, "tokens", tokens, "last_refill", last_refill)
    -- set expiry to capacity / refill_rate to clean up unused keys
    local ttl = math.ceil(capacity / refill_rate) * 2
    redis.call("EXPIRE", key, ttl)
    return {1, tokens} -- 1 means allowed
else
    -- calculate retry_after in seconds
    local deficit = cost - tokens
    local retry_after = math.ceil(deficit / refill_rate)
    redis.call("HMSET", key, "tokens", tokens, "last_refill", last_refill)
    return {0, retry_after} -- 0 means rejected, return retry_after
end
