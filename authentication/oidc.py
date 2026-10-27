from oauth2_provider.oauth2_validators import OAuth2Validator



class DjangoClaimsValidator(OAuth2Validator):
    oidc_claim_scope = {**OAuth2Validator.oidc_claim_scope, "permissions": "openid"}

    # This lists what will be writen in the token
    def get_additional_claims(self, request):
        user = request.user
        return {
            "name": user.get_full_name() or user.get_username(),
            "preferred_username": user.get_username(),
            "email": user.email,
            "permissions": ["default:admin"] if user.is_superuser else [],
        }
